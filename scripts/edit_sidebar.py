"""
Add "Qualidade do Score" link to sidebar in base.html.
"""
BASE_PATH = "/home/william/repos/wins-hub-log/templates/base.html"

with open(BASE_PATH, "r", encoding="utf-8") as f:
    content = f.read()

old = """        <a href=\"/followups\" class=\"menu-item-link {% if request.path == '/followups' %}active{% endif %}\">
          <i class=\"bi bi-calendar-event\"></i>
          <span>Follow-ups</span>
        </a>
      </li>
    </ul>"""

new = """        <a href=\"/followups\" class=\"menu-item-link {% if request.path == '/followups' %}active{% endif %}\">
          <i class=\"bi bi-calendar-event\"></i>
          <span>Follow-ups</span>
        </a>
      </li>
      <li>
        <a href=\"/qualidade-score\" class=\"menu-item-link {% if request.path == '/qualidade-score' %}active{% endif %}\">
          <i class=\"bi bi-bar-chart-steps\"></i>
          <span>Qualidade do Score</span>
        </a>
      </li>
    </ul>"""

if old in content:
    content = content.replace(old, new, 1)
    with open(BASE_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print("Sidebar updated: Qualidade do Score link added.")
else:
    print("ERROR: Could not find the target section in base.html")
    # Debug: show what we have around the followups section
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if "Follow-ups" in line:
            print(f"  Found 'Follow-ups' at line {i+1}: {repr(line)}")
            print(f"  Next lines:")
            for j in range(i, min(i+8, len(lines))):
                print(f"    {j+1}: {repr(lines[j])}")
            break
