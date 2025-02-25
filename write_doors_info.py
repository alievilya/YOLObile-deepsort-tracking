import cv2
import os
import numpy as np

rect_endpoint_tmp = []
rect_bbox = []
drawing = False


def select_object(img):
    """
    Interactive select rectangle ROIs and store list of bboxes.

    Parameters
    ----------
    img :
           image 3-dim.

    Returns
    -------
    bbox_list_rois : list of list of int
           List of bboxes of rectangle rois.
    """

    # mouse callback function
    bbox_list_rois = []

    def draw_rect_roi(event, x, y, flags, param):

        # grab references to the global variables
        global rect_bbox, rect_endpoint_tmp, drawing

        # if the left mouse button was clicked, record the starting
        # (x, y) coordinates and indicate that drawing is being
        # performed. set rect_endpoint_tmp empty list.
        if event == cv2.EVENT_LBUTTONDOWN:
            rect_endpoint_tmp = []
            rect_bbox = [(x, y)]
            drawing = True

        # check to see if the left mouse button was released
        elif event == cv2.EVENT_LBUTTONUP:
            # record the ending (x, y) coordinates and indicate that
            # drawing operation is finished
            rect_bbox.append((x, y))
            drawing = False

            # draw a rectangle around the region of interest
            p_1, p_2 = rect_bbox
            cv2.rectangle(img, p_1, p_2, color=(0, 255, 0), thickness=3)
            cv2.imshow('image', img)

            # for bbox find upper left and bottom right points
            p_1x, p_1y = p_1
            p_2x, p_2y = p_2

            lx = min(p_1x, p_2x)
            ty = min(p_1y, p_2y)
            rx = max(p_1x, p_2x)
            by = max(p_1y, p_2y)

            # add bbox to list if both points are different
            if (lx, ty) != (rx, by):
                bbox = [lx, ty, rx, by]
                bbox_list_rois.append(bbox)

        # if mouse is drawing set tmp rectangle endpoint to (x,y)
        elif event == cv2.EVENT_MOUSEMOVE and drawing:
            rect_endpoint_tmp = [(x, y)]

    # clone image img and setup the mouse callback function
    img_copy = img.copy()
    cv2.namedWindow('image', cv2.WINDOW_NORMAL)
    # cv2.resizeWindow('image', 1200, 600)
    cv2.setMouseCallback('image', draw_rect_roi)

    # keep looping until the 'c' key is pressed
    while True:
        # display the image and wait for a keypress
        if not drawing:
            cv2.namedWindow('image', cv2.WINDOW_NORMAL)
            cv2.resizeWindow('image', img_copy.shape[1], img_copy.shape[0])
            cv2.imshow('image', img)
        elif drawing and rect_endpoint_tmp:
            rect_cpy = img.copy()
            start_point = rect_bbox[0]
            end_point_tmp = rect_endpoint_tmp[0]
            cv2.rectangle(rect_cpy, start_point, end_point_tmp, (0, 255, 0), 3)
            cv2.imshow('image', rect_cpy)

        key = cv2.waitKey(1) & 0xFF
        # if the 'c' key is pressed, break from the loop
        if key == ord('c'):
            break
    # close all open windows
    cv2.destroyAllWindows()

    return bbox_list_rois


def read_door_info(name=None):
    door_info = {}
    with open(name, 'r') as file:
        lines = file.readlines()
    for line in lines:
        line_l = line.split(";")
        val = line_l[1][1:-2].split(",")
        for i, v in enumerate(val):
            val[i] = int(v)
        door_info[line_l[0]] = val
    return door_info


if __name__ == "__main__":
    files = os.listdir('data_files/videos')
    doors_arr = {}
    around_doors_arr = {}
    action_name1 = 'choose door where man is getting lost in frame'
    action_name2 = 'choose region around the door, where the video should start writing'
    print('', action_name1)
    for file in files:
        file_path = os.path.join('data_files/videos', file)
        # file_path = os.path.join("rtsp://admin:admin@192.168.1.52:554/1/h264major")
        video_capture = cv2.VideoCapture(file_path)
        ret, first_frame = video_capture.read()
        cv2.putText(first_frame, "{}".format(action_name1), (10, 35), 0,
                    1e-3 * first_frame.shape[0], (0, 0, 255), 3)
        door = select_object(first_frame)
        doors_arr[file] = door

    print('', action_name2)
    for file in files:
        file_path = os.path.join('data_files/videos', file)
        video_capture = cv2.VideoCapture(file_path)
        ret, first_frame = video_capture.read()
        cv2.putText(first_frame, "{}".format(action_name2), (10, 35), 0,
                    1e-3 * first_frame.shape[0], (0, 0, 255), 3)
        door = select_object(first_frame)
        around_doors_arr[file] = door

    mode = 'a' if os.path.exists('data_files/doors_info.csv') else 'w'
    with open('data_files/doors_info.csv', mode) as f:
        for name in doors_arr.keys():
            f.write(str(name) + ';' + str(doors_arr[name][0]) + '\n')

    mode1 = 'a' if os.path.exists('data_files/around_doors_info.csv') else 'w'
    with open('data_files/around_doors_info.csv', mode1) as f:
        for name in around_doors_arr.keys():
            f.write(str(name) + ';' + str(around_doors_arr[name][0]) + '\n')
    doors_info = read_door_info(name='data_files/doors_info.csv')
    around_doors_info= read_door_info(name='data_files/around_doors_info.csv')
    print(doors_info)
    print(around_doors_info)
