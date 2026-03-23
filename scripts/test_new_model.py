import os
import random
from ultralytics import YOLO
import glob

# Paths
PROJECT_ROOT = r"C:\Users\Acer\Documents\CAPSTONE\web_dashboard_analytics"
MODEL_PATH = os.path.join(PROJECT_ROOT, "datasets", "afternoon_v1", "yolo_runs", "train_afternoon", "weights", "best.pt")
VAL_IMAGES_DIR = os.path.join(PROJECT_ROOT, "datasets", "afternoon_v1", "yolo_dataset", "val", "images")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "datasets", "afternoon_v1", "exports")

def main():
    print(f"Loading custom model from: {MODEL_PATH}")
    if not os.path.exists(MODEL_PATH):
        print("Error: best.pt not found! Has the training fully completed?")
        return

    model = YOLO(MODEL_PATH)

    # Grab a random image from the validation set (the set it didn't train on, but knows the answers for)
    images = glob.glob(os.path.join(VAL_IMAGES_DIR, "*.jpg"))
    if not images:
        print("Error: No validation images found.")
        return
        
    random_image_path = random.choice(images)
    print(f"\nTesting on random validation frame: {os.path.basename(random_image_path)}")

    # Run inference
    results = model(random_image_path, conf=0.25) # 0.25 confidence threshold
    
    # Process results
    result = results[0]
    output_filename = os.path.join(OUTPUT_DIR, f"test_result_{os.path.basename(random_image_path)}")
    
    # Save the annotated image
    result.save(filename=output_filename)
    
    # Print what it found
    boxes = result.boxes
    if len(boxes) == 0:
        print("The model did not detect any children or adults in this frame.")
    else:
        print(f"\nThe model detected {len(boxes)} person(s):")
        for box in boxes:
            class_id = int(box.cls[0])
            conf = float(box.conf[0])
            class_name = model.names[class_id]
            print(f"- {class_name} (Confidence: {conf*100:.1f}%)")
            
    print(f"\nSuccess! Annotated image saved to:\n{output_filename}")

if __name__ == "__main__":
    main()
