import socket

from deep_sort_pytorch.deep_sort import DeepSort
from deep_sort_pytorch.utils.parser import get_config
from models import *  # set ONNX_EXPORT in models.py
from tracking_modules import Counter, Writer
from tracking_modules import find_centroid, Rectangle, rect_square, bbox_rel, draw_boxes, select_object
from utils.datasets import *
from utils.utils import *


def detect(config):
    sent_videos = set()
    video_name = ""

    # door_array = select_object()
    # door_array = [475, 69, 557, 258]
    global flag, vid_writer, lost_ids
    # initial parameters
    door_array = [528, 21, 581, 315]
    around_door_array = [503, 20, 619, 346]
    rect_door = Rectangle(door_array[0], door_array[1], door_array[2], door_array[3])
    rect_around_door = Rectangle(around_door_array[0], around_door_array[1], around_door_array[2], around_door_array[3])
    # socket
    HOST = "localhost"
    PORT = 8084
    # camera info
    save_img = True
    imgsz = (416, 416) if ONNX_EXPORT else config[
        "img_size"]  # (320, 192) or (416, 256) or (608, 352) for (height, width)
    out, source, weights, half, view_img = config["output"], config["source"], config["weights"], \
                                           config["half"], config["view_img"]
    webcam = source == '0' or source.startswith('rtsp') or source.startswith('http') or source.endswith('.txt')
    # initialize deepsort
    cfg = get_config()
    cfg.merge_from_file(config["config_deepsort"])
    # initial objects of classes
    counter = Counter(counter_in=0, counter_out=0, track_id=0)
    VideoHandler = Writer()
    deepsort = DeepSort(cfg.DEEPSORT.REID_CKPT,
                        max_dist=cfg.DEEPSORT.MAX_DIST, min_confidence=cfg.DEEPSORT.MIN_CONFIDENCE,
                        nms_max_overlap=cfg.DEEPSORT.NMS_MAX_OVERLAP, max_iou_distance=cfg.DEEPSORT.MAX_IOU_DISTANCE,
                        max_age=cfg.DEEPSORT.MAX_AGE, n_init=cfg.DEEPSORT.N_INIT, nn_budget=cfg.DEEPSORT.NN_BUDGET,
                        use_cuda=True)

    # Initialize device, weights etc.
    device = torch_utils.select_device(device='cpu' if ONNX_EXPORT else config["device"])
    if os.path.exists(out):
        shutil.rmtree(out)  # delete output folder
    os.makedirs(out)  # make new output folder
    half = device.type != 'cpu'  # half precision only supported on CUDA
    # Initialize model
    model = Darknet(config["cfg"], imgsz)

    # Load weights
    attempt_download(weights)
    if weights.endswith('.pt'):  # pytorch format
        model.load_state_dict(torch.load(weights, map_location=device)['model'], strict=False)
    else:  # darknet format
        load_darknet_weights(model, weights)
    # Eval mode
    model.to(device).eval()
    # Half precision
    half = half and device.type != 'cpu'  # half precision only supported on CUDA
    if half:
        model.half()

    if webcam:
        view_img = True
        torch.backends.cudnn.benchmark = True  # set True to speed up constant image size inference
        dataset = LoadStreams(source, img_size=imgsz)
    else:
        save_img = True
        view_img = True
        dataset = LoadImages(source, img_size=imgsz)

    # Get names and colors
    names = load_classes(config["names"])
    colors = [[random.randint(0, 255) for _ in range(3)] for _ in range(len(names))]

    # Run inference

    img = torch.zeros((1, 3, imgsz, imgsz), device=device)  # init img
    _ = model(img.half() if half else img.float()) if device.type != 'cpu' else None  # run once
    # flag_personindoor = False
    mean_values = []
    median_frame_value = None
    prev_frame = None
    initialize_mean = True

    for frame_idx, (path, img, im0s, vid_cap) in enumerate(dataset):
        if initialize_mean and len(mean_values) < 20:
            mean_values.append(np.mean(im0s[0]))
        else:
            median_frame_value = np.median(mean_values)
            initialize_mean = False
            print(median_frame_value)
        t0 = time.time()
        ratio_detection = 0
        img = torch.from_numpy(img).to(device)
        img = img.half() if half else img.float()  # uint8 to fp16/32
        img /= 255.0  # 0 - 255 to 0.0 - 1.0
        if img.ndimension() == 3:
            img = img.unsqueeze(0)
        # Inference
        t1 = torch_utils.time_synchronized()
        pred = model(img, augment=config["augment"])[0]
        t2 = torch_utils.time_synchronized()
        # to float
        if half:
            pred = pred.float()
        # Apply NMS
        classes = None if config["classes"] == "None" else config["classes"]
        pred = non_max_suppression(pred, config["conf_thres"], config["iou_thres"],
                                   multi_label=False, classes=classes, agnostic=config["agnostic_nms"])
        # Process detections
        gray_img = cv2.cvtColor(im0s, cv2.COLOR_BGR2GRAY)

        if median_frame_value:
            frame_difference = np.max(abs(gray_img-median_frame_value))
            print(frame_difference)


        for i, det in enumerate(pred):  # detections for image i
            if webcam:  # batch_size >= 1
                p, s, im0 = path[i], '%g: ' % i, im0s[i].copy()
            else:
                p, s, im0 = path, '', im0s

            save_path = str(Path(out) / Path(p).name)
            s += '%gx%g ' % img.shape[2:]  # print string
            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  #  normalization gain whwh
            lost_ids = counter.return_lost_ids()

            if det is not None and len(det):
                # Rescale boxes from imgsz to im0 size
                det[:, :4] = scale_coords(img.shape[2:], det[:, :4], im0.shape).round()
                # Print results
                for c in det[:, -1].unique():
                    if names[int(c)] not in config["needed_classes"]:
                        continue
                    n = (det[:, -1] == c).sum()  # detections per class
                    s += '%g %s, ' % (n, names[int(c)])  # add to string
                bbox_xywh = []
                confs = []
                # Write results
                for *xyxy, conf, cls in det:
                    #  check if bbox`s class is needed
                    if names[int(cls)] not in config["needed_classes"]:
                        continue
                    x_c, y_c, bbox_w, bbox_h = bbox_rel(*xyxy)
                    obj = [x_c, y_c, bbox_w, bbox_h]
                    bbox_xywh.append(obj)
                    confs.append([conf.item()])

                    if save_img or view_img:  # Add bbox to image
                        label = '%s %.2f' % (names[int(cls)], conf)
                        plot_one_box(xyxy, im0, label=label, color=colors[int(cls)])

                detections = torch.Tensor(bbox_xywh)
                confidences = torch.Tensor(confs)

                # Pass detections to deepsort
                if len(detections) == 0:
                    continue

        # door_array = select_object(im0)[0]
        # print(door_array[0])

        cv2.rectangle(im0, (int(door_array[0]), int(door_array[1])),
                      (int(door_array[2]), int(door_array[3])),
                      (23, 158, 21), 3)
        cv2.imshow('s', im0)
        cv2.waitKey(1)

        delta_time = (time.time() - t0)
        print('Done. (%.3fs)' % delta_time)
        fps = int(1 / delta_time)



# python detect.py --cfg cfg/csdarknet53s-panet-spp.cfg --weights cfg/best14x-49.pt --source 0
import json

if __name__ == '__main__':
    # subprocess.run("python send_video.py", shell=True)
    # os.system("python send_video.py &")
    with open("cfg/detection_tracker_cfg.json") as detection_config:
        detect_config = json.load(detection_config)
    print(detect_config["cfg"])

    with torch.no_grad():
        detect(config=detect_config)