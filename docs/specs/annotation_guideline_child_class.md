# Child-Class Annotation Guideline

## Labeling Principle

Always use:

> visually classified as children based on body size, proportions, and school-age appearance

Never use:

> detect 13 years old and below

## Classes

- `0: child_like`
- `1: adult_like`

The project is still scoped to triggering warnings from child-like detections only. Adults are labeled to improve negative examples and reduce false positives.

## Child-Like Inclusion Rules

Label as `child_like` when:

- the pedestrian appears school-age based on visible body proportions
- at least half of the body is visible
- the person is in or approaching the crosswalk zone
- the frame is clear enough to assess stature and proportions

## Adult-Like Inclusion Rules

Label as `adult_like` when:

- the pedestrian is clearly adult-looking
- the person is in or approaching the same crosswalk scene
- visibility is sufficient for a usable negative example

## Exclusion Rules

Do not label, or move the frame to review/reject, when:

- the subject is too far away to judge reliably
- motion blur destroys the silhouette
- heavy occlusion hides most of the body
- the subject is riding a bicycle or motorcycle
- the object is a poster, mannequin, sign, or reflection

## Ambiguous Cases

Skip or mark uncertain when:

- child versus adult is genuinely unclear
- only a small body fragment is visible
- glare, rain, or darkness makes proportions unreadable
- a short adult could easily be mistaken for a child

## Bounding Box Rules

- draw the box tightly around the visible body
- include the full head when visible
- do not stretch the box to include shadows
- if the body is cut by the frame edge, box only the visible portion

## Minimum Quality Bar

Prefer rejection instead of weak labels when:

- bbox height would be below roughly 20 px
- the frame is a duplicate of a clearer nearby frame
- the subject is too small for a defensible class label

## Source Policy

The active annotation source is the manually gathered crosswalk footage in `datasets/site_dataset_v1/`. Do not mix legacy external datasets into the active labeling workflow.
