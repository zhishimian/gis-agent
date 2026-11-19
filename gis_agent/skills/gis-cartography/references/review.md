# Visual evidence, 5-point QA and stopping

Before judging symbols, inspect actual geometry types, CRS, NoData masks, encoded field ranges and class counts. Reuse established analytical evidence without repeating heavy computation.

## Pre-render data check
1. Verify vector geometry types, attribute join coverage and CRS units; for rasters check transform, scale/offset, NoData sentinel masking and resampling mode (nearest for classes, bilinear for continuous fields).
2. Confirm that Zero stays distinct from NoData (`#d9d9d9`) and that all panels share consistent class breaks, `norm` bounds and color dictionaries.

## 5-point structured visual QA (after `read_image`)
Run these five checks whenever reviewing `preview.png`:

1. **Screenshot Legibility & Even-Integer Font Ladder**: Inspect `layout_diagnostics["typography"]` and view the whole image zoomed out. Confirm `small_text_warning == False` (`min_font_pt >= 10` and `min_font_height_ratio >= 0.017`), `non_even_font_warning == False` and `fragmented_font_tiers_warning == False` (`<= 4-5` even sizes). Every tick, legend entry and callout must read effortlessly at thumbnail size.
2. **Hygiene Flags, Zero Subtitles/Unrequested Insets & Text-Off-Map Discipline**: Inspect `layout_diagnostics["hygiene"]` and verify `subtitle_detected_warning == False`, `callout_box_warning == False`, `duplicate_axis_ticks_warning == False`, `clipped_text_warning == False` and `frame_overflow_warning == False`. Confirm zero unrequested zoom panels/statistical sidebars, zero stacked subtitles, zero prose/labels sitting awkwardly on mapped thematic landmass, minimal `Variable (unit)` legend titles, and bundled `Source Serif 4` / `LXGW WenKai Lite` print typography (`font_style="serif"`/`"kaiti"`).
3. **Hard Grid Alignment, Neighbor Context, Lower Scalebar & Whitespace**: Confirm panel edges align cleanly (`GridSpec`), `ax_main` renders surrounding non-study states/countries in muted `#efeeea`/`#c4c0b8` ("uncolored yet bordered", never bare white around the study area), compact country-centered circular/rectangular locator insets use a clean dashed focus rectangle without messy cross-axes connector lines, primary boundaries draw on `zorder=8` **above overlaid points**, the `cartographic` scalebar sits in the **lower zone** and `compass_star` sits in an empty corner/ocean, and `margin_whitespace_ratio <= 0.15` per edge (`excessive_margin_warning == False`).
4. **Color Semantics, Perceptual Stretch & Continuous Colorbar Discipline**: Confirm continuous surfaces (>5 breaks) render via `build_perceptual_norm` + `add_continuous_colorbar` with explicit `#f7f7f7` zero and `#d9d9d9` NoData rather than washed-out pale ramps or segmented rectangular boxes, overlaid points stay modest with white halos, zero text overlaps/clips, clear scalebar units and crisp DMS ticks.
5. **Fast Convergence & Layered SVG Finalization**: Batch all visual fixes into 1-2 edits on fast PNG-only renders (`formats=("png",)`). Keep heavy vector plotting fast (`<= 15 s`, no `itertuples` loops) so visual QA rounds stay well within budget; once clean, run one final export with `formats=("png", "svg")` (`svg.fonttype="none"`, `rasterized=True` on continuous rasters/dense layers, `gid` groups) and stop immediately.

Crop only a dense legend or crowded inset when ambiguous. Record analytical caveats outside the map in your text response rather than on the figure face.
