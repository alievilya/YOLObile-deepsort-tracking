import socket
import pycuda.autoinit  # This is needed for initializing CUDA driver
import cv2
import os
import time
import argparse

from deep_sort_pytorch.deep_sort import DeepSort
from deep_sort_pytorch.utils.parser import get_config
from models import *  # set ONNX_EXPORT in models.py
from tracking_modules import Counter, Writer
from tracking_modules import find_centroid, Rectangle, rect_square, draw_boxes
from utils.utils import *
from utils.visualization import BBoxVisualization
from utils.yolo_classes import get_cls_dict
from utils.yolo_with_plugins import get_input_shape, TrtYOLO
from utils.datasets import *

WINDOW_NAME = 'TrtYOLODemo'


def perform_detection(frame, trt_yolo, conf_th, vis):
    """Continuously capture images from camera and do object detection.

    # Arguments
      cap: the camera instance (video source).
      trt_yolo: the TRT YOLO object detector instance.
      conf_th: confidence/score threshold for object detection.
      vis: for visualization.
      writer: the VideoWriter object for the output video.
    """

    if frame is None: print('no frame')
    boxes, confs, clss = trt_yolo.detect(frame, conf_th)
    frame = vis.draw_bboxes(frame, boxes, confs, clss)
    return boxes, confs, clss


def run_detection():
    # args = parse_args()
    with open("cfg/detection_tracker_cfg.json") as detection_config:
        detect_config = json.load(detection_config)

    if detect_config["category_num"] <= 0:
        raise SystemExit('ERROR: bad category_num (%d)!' % detect_config["category_num"])
    if not os.path.isfile('yolo/%s.trt' % detect_config["model"]):
        raise SystemExit('ERROR: file (yolo/%s.trt) not found!' % detect_config["model"])

    cap = cv2.VideoCapture(detect_config["source"])
    if not cap.isOpened():
        raise SystemExit('ERROR: failed to open the input video file!')
    frame_width, frame_height = int(cap.get(3)), int(cap.get(4))

    cls_dict = get_cls_dict(detect_config["category_num"])
    vis = BBoxVisualization(cls_dict)
    h, w = get_input_shape(detect_config["model"])
    trt_yolo = TrtYOLO(detect_config["model"], (h, w), detect_config["category_num"], detect_config["letter_box"])
    ret, frame = cap.read()
    boxes, confs, clss = perform_detection(frame=frame, trt_yolo=trt_yolo, conf_th=0.3, vis=vis)


def xyxy_to_xywh(bbox_xyxy):
    xc = int(bbox_xyxy[0] + bbox_xyxy[2])/2
    yc = int(bbox_xyxy[1] + bbox_xyxy[3])/2
    w = int(abs(bbox_xyxy[2] - bbox_xyxy[0]))
    h = int(abs(bbox_xyxy[3] - bbox_xyxy[1]))
    return (xc, yc, w, h)

def detect(config):
    sent_videos = set()
    video_name = ""
    fpeses = []
    fps = 0

    # door_array = select_object()
    # door_array = [475, 69, 557, 258]
    global flag, vid_writer, lost_ids
    # initial parameters
    # door_array = [528, 21, 581, 315]
    # door_array = [596, 76, 650, 295]  #  18 stream
    door_array = [611, 70, 663, 310]
    # around_door_array = [572, 79, 694, 306]  #
    # around_door_array = [470, 34, 722, 391]
    around_door_array = [507, 24, 724, 374]
    low_border = 225
    #
    door_c = find_centroid(door_array)
    rect_door = Rectangle(door_array[0], door_array[1], door_array[2], door_array[3])
    rect_around_door = Rectangle(around_door_array[0], around_door_array[1], around_door_array[2], around_door_array[3])
    # socket
    HOST = "localhost"
    PORT = 8085
    # camera info
    save_img = True
    imgsz = (256, 256) if ONNX_EXPORT else config[
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
    # Initialize colors
    names = load_classes(config["names"])
    colors = [[random.randint(0, 255) for _ in range(3)] for _ in range(len(names))]

    if config["category_num"] <= 0:
        raise SystemExit('ERROR: bad category_num (%d)!' % config["category_num"])
    if not os.path.isfile('yolo/%s.trt' % config["model"]):
        raise SystemExit('ERROR: file (yolo/%s.trt) not found!' % config["model"])

    # cap = cv2.VideoCapture(config["source"])
    # if not cap.isOpened():
    #     raise SystemExit('ERROR: failed to open the input video file!')
    # frame_width, frame_height = int(cap.get(3)), int(cap.get(4))
    webcam = source == '0' or source.startswith('rtsp') or source.startswith('http') or source.endswith('.txt')
    if webcam:
        torch.backends.cudnn.benchmark = True  # set True to speed up constant image size inference
        dataset = LoadStreams(source, img_size=imgsz)
    else:
        save_img = True
        dataset = LoadImages(source, img_size=imgsz)
    img = torch.zeros((3, imgsz, imgsz), device=device)  # init img
    

    cls_dict = get_cls_dict(config["category_num"])
    vis = BBoxVisualization(cls_dict)
    h, w = get_input_shape(config["model"])
    trt_yolo = TrtYOLO(config["model"], (h, w), config["category_num"], config["letter_box"])

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((HOST, PORT))
        img_shape = (256, 256)
        for frame_idx, (path, img, im0s, vid_cap) in enumerate(dataset):
            t0 = time.time()

            flag_move = False
            flag_anyone_in_door = False
            
            ratio_detection = 0
            # Process detections
            lost_ids = counter.return_lost_ids()
            if webcam:  # batch_size >= 1
                p, s, im0 = path[0], '%g: ' % 0, im0s[0].copy() #TODO mb needed in loop for detection
            else:
                p, s, im0 = path, '', im0s
            
            preds, confs, clss = perform_detection(frame=im0, trt_yolo=trt_yolo, conf_th=config["conf_thres"], vis=vis)

            scaled_pred = []
            scaled_conf = []
            detections = torch.Tensor()
            for i, (det, conf, cls) in enumerate(zip(preds, confs, clss)):

                if det is not None and len(det):
                    # Rescale boxes from imgsz to im0 size
                    
                    if names[int(cls)] not in config["needed_classes"]:
                        continue
                    # Write results
                    det = xyxy_to_xywh(det)
                    #det = scale_coords(img_shape, det, im0.shape)
                    scaled_pred.append(det)
                    scaled_conf.append(conf)

                detections = torch.Tensor(scaled_pred)
                confidences = torch.Tensor(scaled_conf)

                # Pass detections to deepsort
            if len(detections) != 0:

                outputs = deepsort.update(detections, confidences, im0)

                # draw boxes for visualization
                if len(outputs) > 0:
                    bbox_xyxy = outputs[:, :4]
                    # bbox_xywh = xyxy_to_xywh(bbox_xyxy)
	
                    identities = outputs[:, -1]
                    draw_boxes(im0, bbox_xyxy, identities)
                    # print('bbox_xywh ', bbox_xywh, 'id', identities)
                    counter.update_identities(identities)

                    for bbox_tracked, id_tracked in zip(bbox_xyxy, identities):

                        rect_detection = Rectangle(bbox_tracked[0], bbox_tracked[1],
                                                    bbox_tracked[2], bbox_tracked[3])
                        inter_detection = rect_detection & rect_around_door
                        if inter_detection:
                            inter_square_detection = rect_square(*inter_detection)
                            cur_square_detection = rect_square(*rect_detection)
                            try:
                                ratio_detection = inter_square_detection / cur_square_detection
                            except ZeroDivisionError:
                                ratio_detection = 0
                        #  чел первый раз в контуре двери
                        if ratio_detection > 0.2:
                            if VideoHandler.counter_frames_indoor == 0:
                                #     флаг о начале записи
                                VideoHandler.start_video(id_tracked)
                            flag_anyone_in_door = True

                        elif ratio_detection > 0.2 and id_tracked not in VideoHandler.id_inside_door_detected:
                            VideoHandler.continue_opened_video(id=id_tracked, seconds=3)
                            flag_anyone_in_door = True

                        if id_tracked not in counter.people_init or counter.people_init[id_tracked] == 0:
                            counter.obj_initialized(id_tracked)
                            rect_head = Rectangle(bbox_tracked[0], bbox_tracked[1], bbox_tracked[2],
                                                    bbox_tracked[3])
                            intersection = rect_head & rect_door
                            if intersection:
                                intersection_square = rect_square(*intersection)
                                head_square = rect_square(*rect_head)
                                rat = intersection_square / head_square
                                if rat >= 0.3 and bbox_tracked[3] > low_border:
                                    #     was initialized in door, probably going out of office
                                    counter.people_init[id_tracked] = 2
                                elif rat < 0.3:
                                    #     initialized in the corridor, mb going in
                                    counter.people_init[id_tracked] = 1
                            else:
                                # res is None, means that object is not in door contour
                                counter.people_init[id_tracked] = 1
                            counter.frame_age_counter[id_tracked] = 0

                            counter.people_bbox[id_tracked] = bbox_tracked

                        counter.cur_bbox[id_tracked] = bbox_tracked
            else:
                deepsort.increment_ages()

            # Stream results
            vals_to_del = []
            for val in counter.people_init.keys():
                # check bbox also
                inter = 0
                cur_square = 0
                ratio = 0
                cur_c = find_centroid(counter.cur_bbox[val])
                centroid_distance = np.sum(np.array([(door_c[i] - cur_c[i]) ** 2 for i in range(len(door_c))]))

                # init_c = find_centroid(counter.people_bbox[val])
                # vector_person = (cur_c[0] - init_c[0],
                #                  cur_c[1] - init_c[1])

                rect_cur = Rectangle(counter.cur_bbox[val][0], counter.cur_bbox[val][1],
                                     counter.cur_bbox[val][2], counter.cur_bbox[val][3])
                inter = rect_cur & rect_door

                if val in lost_ids and counter.people_init[val] != -1:

                    if inter:
                        inter_square = rect_square(*inter)
                        cur_square = rect_square(*rect_cur)
                        try:
                            ratio = inter_square / cur_square

                        except ZeroDivisionError:
                            ratio = 0
                    # if vector_person < 0 then current coord is less than initialized, it means that man is going
                    # in the exit direction

                    if counter.people_init[val] == 2 \
                            and ratio < 0.4 and centroid_distance > 5000:
                        print('ratio out: {}\n centroids: {}\n'.format(ratio, centroid_distance))
                        counter.get_out()
                        counter.people_init[val] = -1
                        VideoHandler.stop_recording(action_occured="вышел из кабинета")

                        vals_to_del.append(val)

                    elif counter.people_init[val] == 1 \
                            and ratio >= 0.4 and centroid_distance < 1000:
                        print('ratio in: {}\n centroids: {}\n'.format(ratio, centroid_distance))
                        counter.get_in()
                        counter.people_init[val] = -1
                        VideoHandler.stop_recording(action_occured="зашел внутрь")
                        vals_to_del.append(val)

                    lost_ids.remove(val)

                # TODO maybe delete this condition
                elif counter.frame_age_counter.get(val, 0) >= counter.max_frame_age_counter \
                        and counter.people_init[val] == 2:
                    if inter:
                        inter_square = rect_square(*inter)
                        cur_square = rect_square(*rect_cur)
                        try:
                            ratio = inter_square / cur_square
                        except ZeroDivisionError:
                            ratio = 0

                    if ratio < 0.2 and centroid_distance > 10000:
                        counter.get_out()
                        print('ratio out max frames: ', ratio)
                        counter.people_init[val] = -1
                        VideoHandler.stop_recording(action_occured="вышел")
                        vals_to_del.append(val)
                    counter.age_counter[val] = 0

                counter.clear_lost_ids()

            for valtodel in vals_to_del:
                counter.delete_person_data(track_id=valtodel)

            ins, outs = counter.show_counter()
            cv2.rectangle(im0, (0, 0), (250, 50),
                          (0, 0, 0), -1, 8)

            cv2.rectangle(im0, (int(door_array[0]), int(door_array[1])),
                          (int(door_array[2]), int(door_array[3])),
                          (23, 158, 21), 3)

            cv2.rectangle(im0, (int(around_door_array[0]), int(around_door_array[1])),
                          (int(around_door_array[2]), int(around_door_array[3])),
                          (48, 58, 221), 3)

            cv2.putText(im0, "in: {}, out: {} ".format(ins, outs), (10, 35), 0,
                        1e-3 * im0.shape[0], (255, 255, 255), 3)

            cv2.line(im0, (door_array[0], low_border), (880, low_border), (214, 4, 54), 4)

            if VideoHandler.stop_writing(im0):
                # send_new_posts(video_name, action_occured)
                sock.sendall(bytes(VideoHandler.video_name + ":" + VideoHandler.action_occured, "utf-8"))
                data = sock.recv(100)
                print('Received', repr(data.decode("utf-8")))
                sent_videos.add(VideoHandler.video_name)
                with open('data_files/logs2.txt', 'a', encoding="utf-8-sig") as wr:
                    wr.write(
                        'video {}, man {}, centroid {} '.format(VideoHandler.video_name, VideoHandler.action_occured,
                                                                centroid_distance))
                                                            
                print('_________________video was sent _________________')

                VideoHandler = Writer()
                VideoHandler.set_fps(fps)

            else:
                VideoHandler.continue_writing(im0, flag_anyone_in_door)
            if view_img is True:
                cv2.imshow('image', im0)
                cv2.waitKey(1)
                if cv2.waitKey(1) == ord('q'):  # q to quit
                    raise StopIteration

            delta_time = (time.time() - t0)
            # t2_ds = time.time()
            # print('%s Torch:. (%.3fs)' % (s, t2 - t1))
            # print('Full pipe. (%.3fs)' % (t2_ds - t0_ds))
            if len(fpeses) < 15:
                fpeses.append(round(1 / delta_time))
                print(delta_time)
            elif len(fpeses) == 15:
                # fps = round(np.median(np.array(fpeses)))
                fps = np.median(np.array(fpeses))
                # fps = 10
                print('fps set: ', fps)
                VideoHandler.set_fps(fps)
                counter.set_fps(fps)
                fpeses.append(fps)
                motion_detection = True
            else:
                if VideoHandler.flag_writing_video:
                    print('\writing video ') 
                if VideoHandler.flag_stop_writing:
                    print('stop writing') 
                if flag_anyone_in_door:
                    print('anyone in door') 
                if VideoHandler.counter_frames_indoor:
                    print('counter frames indoor: {}'.format(VideoHandler.counter_frames_indoor)) 
        # fps = 20


# python detect.py --cfg cfg/csdarknet53s-panet-spp.cfg --weights cfg/best14x-49.pt --source 0
import json

if __name__ == '__main__':
    # subprocess.run("python send_video.py", shell=True)
    # os.system("python send_video.py &")
    with open("cfg/detection_tracker_cfg.json") as detection_config:
        detect_config = json.load(detection_config)
    print('opening source: {}'.format(detect_config["source"]))
    print('reading model: {}'.format(detect_config["model"]))
    with torch.no_grad():
        detect(config=detect_config)
