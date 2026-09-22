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

1. **(30 s) Plain JPG of a city.** Upload it and fly over the relative DSM. Say it straight: no georeference means no metres, and we don't fake them.
2. **(60 s) Namchi, South Sikkim: a 0.3 m WorldView-3 GeoTIFF calibrated with ISRO's CartoDEM.** A hill town on steep slopes is where "terrain from the DEM, detail from the model" shows.
   - Fly in and click a building so its height shows in metres.
   - Draw a profile line from the valley up through the town.
   - Point out the calibration panel showing which source set the scale.
   - On screen and on the slide: "Imagery: Maxar Open Data Program (CC BY-NC 4.0). CartoDEM Version-3 R1, National Remote Sensing Centre, ISRO, Government of India, Hyderabad, India."
3. **(45 s) Validation.**
   - Open the Austin scene (a NAIP + USGS 3DEP test site) and upload its LiDAR DSM. The files are in the demo kit, "1 Upload live\C Validate (Austin)". DFC2019 access never came through.
   - The error heatmap and RMSE appear live. The bias includes the datum gap between the LiDAR (NAVD88) and the DEM (EGM2008).
4. **(45 s) Results.** Show the per-landscape table against the DEM-only baseline, plus one failure case and its cause.

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
| Where do metres come from for a plain JPG? | They don't. It's a relative DSM. An optional known-height anchor gives approximate metres, flagged low confidence. |
| What's the accuracy on Indian data? | We couldn't find public LiDAR for Indian cities. We tested on DFC2019 and USGS 3DEP, and Indian scenes are shown qualitatively. We'd validate on ISRO reference data given access. |
| Why Depth Anything V2? | The problem statement allows a pretrained backbone. Small runs on an 8 GB laptop GPU, it's Apache-2.0, and a published remote-sensing fine-tune of it exists (Depth Any Canopy). |
| Tall buildings lean in satellite images. | Known. It's in our failure gallery. The fix is to use the view-angle metadata. |
| How fast is it? | Read from the runtime table. |
| What about vertical datums? | We report raw and offset-free RMSE, and list the datum of every source. |
| What would you do with more time? | Fine-tune on ISRO data, estimate height from shadow length using sun-angle metadata, and mask water. |

Answers must match what the build actually does on presentation day. If a feature got cut, change the answer.

## Rehearsal checklist

- [ ] Two timed run-throughs, both under the time limit
- [ ] Every number on the slides traced to a run in evals/results/
- [ ] Backup video: a screen recording of the full 3-minute demo
- [ ] Demo tested with Wi-Fi off
- [ ] Every teammate can answer at least two of the questions above
- [ ] Printed architecture diagram, in case the projector fails
