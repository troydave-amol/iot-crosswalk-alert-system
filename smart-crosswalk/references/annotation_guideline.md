# Child-Class Annotation Guideline

## Labeling Principle (Use Everywhere)

ALWAYS use:
> "visually classified as children based on body size, proportions, and school-age appearance"

NEVER use:
> "detect 13 years old and below" (biological age claim — out of scope)

---

## Class Definition

**Class 0: child**
A pedestrian who appears to be a school-age child based on:
- Body proportions: shorter stature, larger head-to-body ratio compared to adults
- School context cues: backpack, school uniform, smaller frame
- Approximate height relative to environment (e.g., below vehicle window line)

---

## Inclusion Rules

Label as `child` when:
- Full or mostly visible body (>50% visible) shows child proportions
- Visible in the crosswalk or approach zone
- Adequate image resolution to assess proportions (min ~20px height in image)

---

## Exclusion Rules

Do NOT label (mark as difficult or skip):
- Adults, even if carrying children
- Ambiguous cases — if unsure, use `uncertain` tag or skip
- Children on bicycles (out of scope for pedestrian detection)
- Mannequins, dolls, school signs

---

## Ambiguous Cases → "skip/uncertain"

When the following apply, skip the annotation:
- Person is too far away (<20px bounding box height)
- Heavy occlusion (>70% of body blocked)
- Motion blur makes proportions unclear
- Adult of short stature that could be confused

---

## Bounding Box Rules

- Draw the bbox tightly around the entire visible body
- Include head fully
- Do NOT extend bbox to include shadows or carried items that extend far
- For partially visible pedestrians at frame edge: include only the visible portion

---

## Occlusion Rules

| Occlusion Level | Action |
|---|---|
| 0–30% | Annotate normally |
| 30–70% | Annotate if proportions still assessable |
| >70% | Skip (mark uncertain) |

---

## Ignore Cases

Do not annotate if:
- Person is behind glass (glare making proportions unclear)
- Very small object (<20px height)
- Pedestrian is clearly adult
- Out of the crosswalk ROI and not approaching

---

## Dataset Sources

- **CityPersons**: Use as pedestrian baseline — NOT child/adult labeled by default. Re-label child instances meeting the inclusion rules above.
- **JAAD**: Provides road/crosswalk behavioral context. Apply same labeling rules.
- **Custom collection**: Priority source for child-class fine-tuning.
