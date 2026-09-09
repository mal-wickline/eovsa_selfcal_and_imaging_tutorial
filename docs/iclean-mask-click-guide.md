# `iclean` mask controls: exact click sequence

See the [illustrated 2024-05-14 mask-making reference](../examples/2024-05-14-x8.8/mask-making-reference/README.md) for the pre-mask SPW survey and screenshots of accepted masks. The older screenshots labeled `mask_spw_5-6` illustrate the low-frequency mask shape; the production configuration uses the solve group `3~6` represented by SPW 5.

The image toolbar is the vertical strip immediately to the right of the raster.
From its top, the relevant icons are **Pan**, **Lasso Mask**, **Box Mask**,
**Wheel Zoom**, **Poly Mask**, **Save**, and **Reset**. Below the horizontal
divider are **Mask Add** (brush/plus), **Mask Sub** (eraser/minus), **Mask
Select**, and **Mask Delete** (trash).

For an EOVSA single-channel MFS mask:

1. Click **Lasso Mask**, the loop-shaped second icon below Pan.
2. Press and hold the primary mouse button just outside the true source.
3. Trace one closed loop around the connected bright source, including a small
   orange buffer but excluding detached sidelobes. Release to close the lasso.
4. Click **Mask Add**, the first black icon below the divider. Keyboard shortcut
   `a` performs the same current-channel operation.
5. Confirm the mask overlay appears. The top `contour` selector controls its
   display style.
6. For this event, leave `nmajor=-1`, `threshold=0.0`, `nsigma=0.0`, and
   `cyclefactor=1.0`. Set `gain=0.05`, `cycleniter=25`, and `niter=100`.
7. Click the **single circular-arrow** button immediately right of the red stop
   button. Wait for that one major cycle to finish.
8. Revise the mask if needed. To remove an area, draw over it and click **Mask
   Sub** (or press `s`). Do not click the trash icon unless the whole mask for
   this channel should be erased.
9. When satisfied, click the **red stop** button and confirm exit. This closes
   the GUI, saves the CASA `.mask`, and returns control to the Python workflow.

The controller exports the resulting `.mask`, `.residual`, and `.image` CASA
products to FITS alongside the originals so they can be inspected directly in
CARTA.

For every event group, mask the connected yellow/orange central source and a
small buffer. Do not include detached orange patches or the broad purple
sidelobe pattern. The 2024-05-14 groups and representative browser images were
SPWs `3~6` (display SPW 5), `7~14` (12), `15~22` (18), and `23~31` (24).
