
import os
import re

import os
import re

implicit_dir = r"C:\Users\raulc\.gemini\antigravity\implicit"
candidates = [
    "5b7174f7-59cc-4572-a6ae-9020c16ef099.pb",
    "0939026b-248a-42b3-9b0c-308a605f9594.pb",
    "e33d831c-ebbd-4943-9072-57dd48dc077e.pb",
    "e0d8d41f-3b1e-44ba-90a8-a758f7cbe1f2.pb"
]

print(f"Checking candidates in {implicit_dir}...\n")

for filename in candidates:
    filepath = os.path.join(implicit_dir, filename)
    try:
        with open(filepath, "rb") as f:
            content = f.read()
        
        print(f"File: {filename}")
        print(f"  Size: {len(content)} bytes")
        
        # Try to find "Organizing" or "Agent System"
        found = False
        if re.search(rb'organizing', content, re.IGNORECASE):
            print("  MATCH FOUND: 'Organizing'")
            found = True
        if re.search(rb'agent system', content, re.IGNORECASE):
            print("  MATCH FOUND: 'Agent System'")
            found = True
            
        if not found:
            # Print first few strings anyway
            strings = re.findall(rb'[ -~]{4,}', content)
            decoded_strings = []
            for s in strings:
                try: 
                    ds = s.decode('utf-8')
                    if len(ds) > 4: decoded_strings.append(ds)
                except: pass
            print(f"  Snippet: {decoded_strings[:20]}")
    except Exception as e:
        print(f"  Error reading {filename}: {e}")
    print("-" * 30)


