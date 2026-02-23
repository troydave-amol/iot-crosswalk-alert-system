import cv2
from cv_inference import ChildLikeDetector, ROI

MODEL_PATH = r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\models\yolov8_childlike_best.pt"
VIDEO_PATH = r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics\datasets\jaad_source\JAAD\JAAD_clips\video_0005.mp4"

# TEMP ROI for testing only (replace with your real saved ROI later)
# You will adjust these numbers after you confirm frame size.
ROI_TEST = ROI(x1=200, y1=200, x2=900, y2=650)

def main():
    det = ChildLikeDetector(MODEL_PATH, conf_child=0.65)

    cap = cv2.VideoCapture(VIDEO_PATH)
    if not cap.isOpened():
        raise SystemExit(f"Cannot open video: {VIDEO_PATH}")

    printed = 0
    frame_shape_printed = False
    
    while True:
        ok, frame = cap.read()
        if not ok:
            break
            
        if not frame_shape_printed:
            print(f"FRAME RESOLUTION (shape): {frame.shape}")
            frame_shape_printed = True

        out = det.infer_frame(frame, ROI_TEST)

        # print occasionally so logs are readable
        printed += 1
        if printed % 30 == 0:
            print(f"SAMPLE DICT: {out}")

    cap.release()
    print("done")

if __name__ == "__main__":
    main()
