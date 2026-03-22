"""
fix_batch1_urls.py
Fix the image URLs for the 1-100 batch in Label Studio's database.
Changes: http://localhost:8095/filename.jpg -> http://localhost:8095/1-100/filename.jpg
"""

import sqlite3
import json

db_path = r"C:\Users\Acer\AppData\Local\label-studio\label-studio\label_studio.sqlite3"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Find the project with 1-100 frames
cursor.execute("SELECT id, title FROM project")
projects = cursor.fetchall()
print("Projects found:")
for pid, title in projects:
    count = cursor.execute("SELECT COUNT(*) FROM task WHERE project_id = ?", (pid,)).fetchone()[0]
    print(f"  ID={pid}: '{title}' ({count} tasks)")

# Fix URLs in project 1 (the 1-100 batch)
PROJECT_ID = 1
cursor.execute("SELECT id, data FROM task WHERE project_id = ?", (PROJECT_ID,))
tasks = cursor.fetchall()

fixed = 0
for tid, data_str in tasks:
    data = json.loads(data_str)
    img_url = data.get("image", "")
    
    # Only fix URLs that DON'T already have a subfolder
    if "localhost:8095/" in img_url and "/1-100/" not in img_url:
        filename = img_url.split("/")[-1]
        new_url = f"http://localhost:8095/1-100/{filename}"
        data["image"] = new_url
        cursor.execute("UPDATE task SET data = ? WHERE id = ?", (json.dumps(data), tid))
        fixed += 1
        if fixed <= 3:
            print(f"  Fixed task {tid}: .../{filename} -> .../1-100/{filename}")

conn.commit()
conn.close()

print(f"\nFixed {fixed} task URLs in project {PROJECT_ID}")
print("Restart Label Studio for changes to take effect.")
