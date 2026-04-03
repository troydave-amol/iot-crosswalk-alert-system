import zipfile
import re

def strip_ls_hash(filename):
    if "__" in filename:
        return filename.split("__", 1)[1]
    return filename

def parse_filename(pure_stem):
    # Example format matchers
    # dense_aft_245_315_01_0086s
    m1 = re.match(r"dense_(aft_\d+_\d+_\d+)_0*(\d+)s", pure_stem)
    if m1: return m1.group(1), float(m1.group(2)), True
    
    # aft_400_445_02_dense_0001_t301s
    m2 = re.match(r"(aft_\d+_\d+_\d+)_dense_\d+_t(\d+)s", pure_stem)
    if m2: return m2.group(1), float(m2.group(2)), True

    # aft_400_445_02_dense_0010.0s or aft_500_545_03_dense_366.0s
    m3 = re.match(r"(aft_\d+_\d+_\d+)_dense_(\d+\.?\d*)s", pure_stem)
    if m3: return m3.group(1), float(m3.group(2)), True
    
    # aft_400_445_02_dense_89s_94s_0010
    m4 = re.match(r"(aft_\d+_\d+_\d+)_dense_(\d+)s_(\d+)s_(\d+)", pure_stem)
    if m4:
        start_sec = int(m4.group(2))
        end_sec = int(m4.group(3))
        seq = int(m4.group(4))
        # Assuming dense segments were extracted at 1 frame per 1 or 2 seconds?
        # If we assume 1 frame per second:
        # timestamp = start_sec + (seq * 1) Wait! In previous dense script, seq starts at 0 or 1?
        return m4.group(1), float(start_sec) + seq, True

    # aft_245_315_03_dense_002
    m5 = re.match(r"(aft_\d+_\d+_\d+)_dense_(\d+)", pure_stem)
    if m5:
        # Without a timestamp anchor, we CANNOT KNOW where this dense segment started or the interval!
        # Unless we know the specific script time boundaries...
        return m5.group(1), f"UNKNOWN_DENSE_SEQ_{m5.group(2)}", True
        
    # sparse: aft_400_445_02_00079
    m_sparse = re.match(r"(aft_\d+_\d+_\d+)_0*(\d+)", pure_stem)
    if m_sparse:
        return m_sparse.group(1), int(m_sparse.group(2)), False
        
    return None, None, None

with zipfile.ZipFile('datasets/exports/Afternoon_V1.zip', 'r') as zf:
    txt_files = [f for f in zf.namelist() if f.startswith('labels/') and f.endswith('.txt')]
    failures = []
    successes = []
    for f in txt_files:
        name = strip_ls_hash(f.split('/')[-1])
        stem = name.replace('.txt', '')
        v_stem, val, is_dense = parse_filename(stem)
        
        if v_stem is None or str(val).startswith("UNKNOWN"):
            failures.append(stem)
        else:
            successes.append((stem, v_stem, val, is_dense))
            
    print(f"Successes: {len(successes)}")
    print(f"Failures:  {len(failures)}")
    if failures:
        print("First 10 Failures:")
        for f in failures[:10]:
            print(f"  {f}")
