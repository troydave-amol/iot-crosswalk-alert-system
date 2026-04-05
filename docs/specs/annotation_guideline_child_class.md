# Child-Class Annotation Guideline

## Wording Rule

Always describe the target as:

> visually classified as children based on body size, proportions, and school-age appearance

Do not describe the system as biological age estimation.

## Current Repo Reality

The repository currently contains two competing class-order conventions:

- current runtime and archived merged dataset behavior:
  - `0 = adult`
  - `1 = child`
- manual scaffold scripts in `scripts/setup_datasets.py` and `scripts/split_dataset.py`:
  - `0 = child_like`
  - `1 = adult_like`

Until that mismatch is resolved, do not assume a newly exported dataset is plug-and-play with the current runtime.

## Recommended Semantic Labels

When discussing annotations in manuscripts, docs, or review:

- positive class: `child_like`
- negative class: `adult_like`

When wiring a concrete dataset into training or deployment, verify the actual numeric class map in that dataset's `data.yaml` before proceeding.

## Child-Like Inclusion Rules

Label a person as child-like when:

- the person appears school-age based on visible proportions and stature
- at least half of the body is visible
- the frame is clear enough to support a defensible judgment
- the person is in, entering, or approaching the crosswalk scene of interest

## Adult-Like Inclusion Rules

Label a person as adult-like when:

- the person is clearly adult-looking in the same scene context
- enough of the body is visible to make the label useful as a negative example
- the frame quality is good enough for consistent review

## Exclusion Rules

Reject or skip frames when:

- the subject is too small or distant to classify with confidence
- motion blur removes useful body-shape cues
- glare, rain, darkness, or occlusion obscures most of the body
- the subject is riding a bicycle or motorcycle
- the object is a reflection, sign, poster, mannequin, or other non-person artifact

## Ambiguous Cases

Prefer exclusion over weak labels when:

- child versus adult is genuinely unclear
- only a fragment of the body is visible
- a short adult could reasonably be mistaken for a child
- the frame is a lower-quality duplicate of a better nearby frame

## Bounding Box Rules

- draw the box tightly around the visible body
- include the head when visible
- do not expand the box to include shadows or empty background
- if the body is cut by the frame edge, annotate only the visible portion

## Dataset Handling Rule

Before training or deployment, check all three of these together:

1. the annotation guideline used by reviewers
2. the `data.yaml` class order for the dataset being trained
3. the class ID the runtime currently treats as the child trigger class

If any one of those disagrees, treat it as a blocking integration issue rather than a documentation detail.
