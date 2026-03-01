# Smart Crosswalk Capstone - Easy Guide

Welcome to the **Smart Crosswalk Project**! Imagine you're building a super smart robot whose only job is to watch a crosswalk and light up a warning sign to keep kids safe when they are crossing the street.

This guide will explain what all the files and folders do, how we taught the robot (Artificial Intelligence), and how everything connects to work perfectly!

---

## 1. How the Project is Organized (Folder Structure)

Think of our project folder like a giant Lego kit. Instead of just throwing all the Lego pieces in one box, we organized them into smaller boxes so we always know where things are.

We use a **3-Layer System** to keep our robot perfectly organized:

### The "What to Do" Layer (Like the Instruction Manual)
*   **Folder:** `docs/specs/`
*   **What it is:** These are text files written in Markdown (a simple way to write reports). They act like the "Boss" of the project.
*   **Why it's important:** These files contain the absolute rules. For example, one file says, *"Only turn on the light for kids, not adults, and don't try to guess exactly how old they are."* In adult terms, this is our "Scope Document."

### The "Doing the Work" Layer (Like the Little Construction Workers)
*   **Folder:** `scripts/`
*   **What it is:** These are Python files (code files) designed to do exactly one job perfectly, over and over again. 
*   **Why it's important:** Instead of a human manually sorting thousands of photos, we run a script (like `setup_datasets.py`) to do it perfectly without making spelling mistakes or getting tired.

### The Raw Materials and The Brain
*   **Folder:** `datasets/`
    *   This is where we keep thousands of pictures and videos of streets, cars, and people. It's the "textbooks" our robot reads to learn what a crosswalk looks like.
*   **Folder:** `models/`
    *   This is the robot's actual "Brain." After the robot studies the textbooks, it saves the things it learned here as a special file (like `yolov8_childlike_best.pt`). If we turn the robot off and back on, it loads this brain file so it doesn't forget anything.
*   **Folder:** `runs/`
    *   This is the robot's "Report Card." It holds graphs and test scores showing us how accurate the robot is.

### The "Face" of the Robot (The Dashboard)
*   **File:** `app.py`
    *   This is the main control room! It creates the website (dashboard) you look at in your web browser. It talks to the database to save history and streams the live video.
*   **File:** `cv_inference.py`
    *   This is the robot's "Eyeballs." It uses the brain (`models/`) to look at the live video and furiously draw little invisible boxes around anyone that looks like a child.
*   **File:** `warning_controller.py`
    *   This is the "Light Switch". If the eyeballs see a child stepping into the crosswalk, this file physically flips the warning switch to "ON". Crucially, it leaves the light on for 2 extra seconds *after* the child leaves, just to be super safe.
*   **File:** `db.py`
    *   This is the "History Book." Every time the warning light turns on or off, it grabs a pen and writes down the exact time it happened in our database (MySQL) so we can look at charts later.

---

## 2. Teaching the Robot (Artificial Intelligence)

Teaching our Artificial Intelligence (AI) was a lot like sending it to school. We did it in two big phases.

### Phase 1: General Pedestrian School 🏫
First, the robot didn't know what a human was. We gave it a massive textbook called the **CityPersons Dataset** (thousands of photos of busy streets). We taught it, *"This moving thing on two legs is a person."* We didn't care if it was a kid or an adult yet, just a person.

### Phase 2: Child Safety Specialty Class 🧒
Once it mastered what a person was, we gave it a harder textbook called the **JAAD Dataset** (videos of people mostly at crosswalks). 

Here is where the strict rules came in. We took a red marker and only circled pedestrians that *looked* like school children. How did we decide?
1.  **Body Size:** Smaller bodies compared to adults.
2.  **Head-to-Body Ratio:** Kids have bigger heads compared to their small bodies.
3.  **School Items:** People wearing backpacks or school uniforms.

If the person looked like an adult, or if they were riding a bicycle, or if they were hiding behind a tree (too hard to see), we told the robot, *"Ignore them!"* 

**The exciting part:** The robot officially graduated Phase 2, and its final smart brain (`models/yolov8_childlike_best.pt`) is fully saved and working!

---

## 3. Is the Robot Ready for a Demo?

**YES! The entire system is working right now like a well-oiled machine.**

Here is exactly what happens when you turn it on (by typing `python app.py` and opening your web browser):

1.  **Opening its Eyes:** The dashboard immediately loads and starts playing a demo video acting as the "Live Camera Feed."
2.  **Activating the Brain:** It loads its smart brain (`models/yolov8_childlike_best.pt`) instantly.
3.  **Watching the Crosswalk:** You will see an invisible "Safe Zone" drawn on the video. This is the **Region of Interest (ROI)**.
4.  **The Trigger Event:** Frame by frame, the robot's eyes scan. If it spots a child, it calculates if they stepped inside the Safe Zone box.
5.  **Flashing the Lights:** As soon as a child steps into the box, the `warning_controller.py` says, **"LIGHTS ON!"** The database writes down the exact millisecond this happened.
6.  **Viewing the History**: If you click the "Logs" or "Analytics" tabs on the dashboard, you instantly see beautiful graphs counting exactly how many times the lights turned on today.

Everything talks to each other perfectly, ensuring kids cross safely and the system logs every successful detection!

Think of ROI as: “Only care about detections inside this rectangle.”

### Correct workflow

1. Go to **Settings → ROI**
2. Use an image that matches your actual camera view:

   * best: take a snapshot from your webcam feed
   * or any still frame from your test video
3. Draw a rectangle **only on the crosswalk area** (where pedestrians will be)
4. Save ROI
5. Go to **Live View**
6. Make sure the place where your “child test content” appears (phone screen or person) is **inside the ROI box**
7. Only then expect `child_in_roi = true`