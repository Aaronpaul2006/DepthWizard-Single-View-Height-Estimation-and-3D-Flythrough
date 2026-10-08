# Pitch and demo

## Slides

Download the official SIH 2026 idea template from the portal and use it as-is. Map our content onto its sections like this:

1. **Title.** SIH26175, "DepthWizard: Single-View Height Estimation and 3D Flythrough", team name, team ID, ISRO, Software.
2. **Idea.** One image in, a height map in metres out, and you can fly through it. The core line: "The DEM gives us the terrain. The model gives us what a 30 m DEM can't see."
3. **Technical approach.**
   - the pipeline diagram from ARCHITECTURE.md
   - Method B in one picture: DEM + scaled model detail = DSM
   - the stack
4. **Feasibility.**
   - it runs today on an 8 GB laptop GPU (runtime table from REPORT.md)
   - the risks and what we do about each
   - the known failure cases
5. **Impact.** Keep it concrete:
   - building-height maps for flood and damage assessment where no LiDAR exists
   - quick 3D terrain previews for planners
   - building-level detail on top of Cartosat imagery and CartoDEM, which ISRO already has
6. **References.**
   - Depth Anything V2 (arXiv 2406.09414)
   - Depth Any Canopy (arXiv 2408.04523)
   - IEEE GRSS DFC2019
   - USGS 3DEP
   - CartoDEM (Bhuvan)
   - Copernicus DEM
   - Three.js

Every accuracy number on a slide comes from evals/results/. E checks each one against its run id before the deck is final.

## Demo script (3 minutes)

Open with the wow, then the problem: judges decide in the first minute. Problem about 30 %, demo about 70 %. Say out loud which half of the rubric each part serves ("that's the accuracy half", "that's the visualisation half").

1. **(40 s) Namchi, South Sikkim: the flip.** Namchi is already open, with Quality set to "Detail · 1024" and the Slope surface on.
   - Press **B**: "This is ISRO's 30 m CartoDEM on its own. The hill is there, the town isn't."
   - Press **B** again: "This is DepthWizard: the same terrain, plus every building." Then give the problem in one line.
   - Switch to Orthophoto, fly in and click a building so its height shows in metres. Draw a profile from the valley up through the town. Press B once more with the profile drawn; the profile swaps too.
   - Point out the calibration panel (which source set the scale).
   - On screen and on the slide: "Imagery: Maxar Open Data Program (CC BY-NC 4.0). CartoDEM Version-3 R1, National Remote Sensing Centre, ISRO, Government of India, Hyderabad, India."
2. **(30 s) Flood, on Austin.** Open the Austin result and drag **Water level**: the river rises, then the low streets, and the panel reads the share of the city under water. This is the disaster-response use case, on a real DSM.
3. **(40 s) Validation.**
   - Still on Austin, upload its LiDAR DSM (demo kit, "1 Upload live\C Validate (Austin)"). DFC2019 access never came through.
   - The error heatmap and RMSE appear live. The bias includes the datum gap between the LiDAR (NAVD88) and the DEM (EGM2008).
4. **(20 s) Plain JPG.** Open the plain photo: relative heights, no metres. Say it straight: no georeference means no metres, and we don't fake them.
5. **(50 s) Results.** Show the per-landscape table against the DEM-only baseline, one failure case and its cause, and the two things we found in the data (CartoDEM is ellipsoidal, checked on three tiles across India; the worst tile is noise in the USGS LiDAR itself). Mention the GAMUS fine-tune honestly: much better on GAMUS test, not better on the LiDAR tiles, so the app keeps the stock model (numbers from `evals/results/gamus_test-20260923-170053` and PLAN.md).

Hand the judge the mouse at the end: "click any building", or "give us any GeoTIFF".

Before the demo:
- the app is open and the model is already loaded
- demo files are on the desktop
- Wi-Fi is off for the scripted demo but available as a fallback: a new image of an area the app hasn't seen needs its Copernicus DEM downloaded once
- the demo kit is on the desktop (`DepthWizard Demo Kit`, with `START HERE - Demo guide.txt`)
- the backup video is one click away

## Likely judge questions

| Question | Answer |
|---|---|
| Height from one image is ill-posed. Why trust this? | The DEM supplies the terrain. The model only adds local detail. The table shows the gain over DEM alone, and where it fails. |
| Where do metres come from for a plain JPG? | They don't. It's a relative DSM, shown in %. If the user types the ground sample distance, horizontal distances become approximate metres (labelled "approximate scale"); heights stay relative. |
| What's the accuracy on Indian data? | We couldn't find public LiDAR for Indian cities. We tested on USGS 3DEP LiDAR (72 tiles, four landscapes) and GAMUS, and Indian scenes are shown qualitatively. We'd validate on ISRO reference data given access. |
| Didn't you just ask an AI to build this? | We used AI tools to write code faster. The decisions came from measuring: 72 LiDAR tiles, a DEM-only baseline, tuning only on val, and two findings in the data (CartoDEM is ellipsoidal; the worst tile is noise in the USGS LiDAR). Ask us about any of them. |
| Why Depth Anything V2? | The problem statement allows a pretrained backbone. Small runs on an 8 GB laptop GPU, it's Apache-2.0, and a published remote-sensing fine-tune of it exists (Depth Any Canopy). |
| Tall buildings lean in satellite images. | Known. It's in our failure gallery. The fix is to use the view-angle metadata. |
| How fast is it? | Read from the runtime table. |
| What about vertical datums? | We report raw and offset-free RMSE, and list the datum of every source. We found CartoDEM V3R1 is ellipsoidal on all three tiles we checked (Sikkim, Ahmedabad, Hyderabad): it sits 38–75 m below Copernicus, matching the local EGM2008 geoid to within about 2 m, and the app corrects it (`evals/results/datum-20260924-103041`). |
| What would you do with more time? | Retune the calibration for the GAMUS fine-tuned model (it already beats the stock model on GAMUS test), fine-tune on ISRO data, estimate height from shadow length using sun-angle metadata, and mask water. |

Answers must match what the build actually does on presentation day. If a feature got cut, change the answer.

## Rehearsal checklist

- [ ] Two timed run-throughs, both under the time limit
- [ ] Every number on the slides traced to a run in evals/results/
- [ ] Backup video: a screen recording of the full 3-minute demo
- [ ] Demo tested with Wi-Fi off
- [ ] Every teammate can answer at least two of the questions above
- [ ] Printed architecture diagram, in case the projector fails
