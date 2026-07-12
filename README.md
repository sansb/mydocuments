# mydocuments.biz

A portrait of Sean built from ~2,700 draggable-ish HTML elements, arranged
like a topography map: brighter features sit "higher" (bigger, closer,
deeper shadows). Moving your mouse across it scatters the pieces. There is
a bio hidden underneath.

## How it works

- `build_portrait.py` samples `sean.jpeg` on a 104x120 grid, flood-fills
  the wall out as elevation 0, quadtree-merges flat regions into bigger
  blocks, and bakes everything into a single self-contained
  `docs/index.html` (no dependencies, no image on the wire).
- `docs/` is what GitHub Pages serves at [mydocuments.biz](https://mydocuments.biz).

## Regenerate

```sh
python3 build_portrait.py   # requires Pillow
```

Never edit `docs/index.html` by hand; edit the template inside the
generator and rerun it.
