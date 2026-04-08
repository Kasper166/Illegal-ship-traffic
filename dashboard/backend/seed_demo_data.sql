-- =============================================================================
-- DARKWATER - Demo Seed Data
-- Gulf of Guinea dark vessel detection records + model metrics progression
-- Safe to run multiple times: inserts only when tables are empty.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- detection_records  (50 rows, inserted only if table is currently empty)
-- ---------------------------------------------------------------------------
INSERT INTO detection_records (
    patch_id, tile_id, bbox_xyxy, pixel_coords, confidence, class_label,
    lat, lon, timestamp, scene_id, flagged_for_review, is_dark,
    metadata, created_at
)
SELECT
    v.patch_id, v.tile_id, v.bbox_xyxy::json, v.pixel_coords::json,
    v.confidence, v.class_label,
    v.lat, v.lon,
    v.ts::timestamptz, v.scene_id,
    v.flagged_for_review, v.is_dark,
    NULL::json,
    v.ts::timestamptz
FROM (VALUES
    -- ---- HIGH CONFIDENCE ~0.70-0.95 (rows 1-30) -------------------------
    -- Cluster near Lagos approach (approx 3.3N, 3.4E)
    ('patch_0001','patch_0001','[88,72,164,138]',  '[88,72,164,138]',  0.93,'vessel',       3.312,  3.418, '2026-03-09T04:12:00Z','S1A_IW_GRDH_20260309T041200_001', false, false),
    ('patch_0002','patch_0002','[210,105,286,173]','[210,105,286,173]',0.91,'vessel',       3.289,  3.452, '2026-03-09T04:12:00Z','S1A_IW_GRDH_20260309T041200_001', false, false),
    ('patch_0003','patch_0003','[44,130,118,196]', '[44,130,118,196]', 0.87,'large_vessel', 3.301,  3.389, '2026-03-11T05:34:00Z','S1A_IW_GRDH_20260311T053400_002', false, false),
    ('patch_0004','patch_0004','[133,88,207,152]', '[133,88,207,152]', 0.85,'vessel',       3.274,  3.471, '2026-03-11T05:34:00Z','S1A_IW_GRDH_20260311T053400_002', false, false),
    ('patch_0005','patch_0005','[67,44,141,108]',  '[67,44,141,108]',  0.84,'large_vessel', 3.330,  3.405, '2026-03-13T06:18:00Z','S1A_IW_GRDH_20260313T061800_003', false, false),
    -- Cluster near Cotonou/Benin coast (6.2N, 2.4E)
    ('patch_0006','patch_0006','[155,92,231,156]', '[155,92,231,156]', 0.92,'vessel',       6.218,  2.387, '2026-03-14T03:50:00Z','S1A_IW_GRDH_20260314T035000_004', false, false),
    ('patch_0007','patch_0007','[78,118,152,184]', '[78,118,152,184]', 0.89,'vessel',       6.193,  2.411, '2026-03-14T03:50:00Z','S1A_IW_GRDH_20260314T035000_004', false, false),
    ('patch_0008','patch_0008','[199,55,275,119]', '[199,55,275,119]', 0.88,'large_vessel', 6.235,  2.362, '2026-03-16T07:22:00Z','S1A_IW_GRDH_20260316T072200_005', false, false),
    ('patch_0009','patch_0009','[112,143,188,209]','[112,143,188,209]',0.86,'vessel',       6.201,  2.398, '2026-03-16T07:22:00Z','S1A_IW_GRDH_20260316T072200_005', false, false),
    -- Mid-Gulf open water scatter
    ('patch_0010','patch_0010','[34,67,108,131]',  '[34,67,108,131]',  0.83,'vessel',       1.847,  4.923, '2026-03-17T08:45:00Z','S1A_IW_GRDH_20260317T084500_006', false, false),
    ('patch_0011','patch_0011','[244,88,318,154]', '[244,88,318,154]', 0.81,'vessel',       0.634,  5.711, '2026-03-18T04:30:00Z','S1A_IW_GRDH_20260318T043000_007', false, false),
    ('patch_0012','patch_0012','[166,204,242,270]','[166,204,242,270]',0.79,'vessel',      -0.218,  6.044, '2026-03-19T09:11:00Z','S1A_IW_GRDH_20260319T091100_008', false, false),
    ('patch_0013','patch_0013','[88,37,162,101]',  '[88,37,162,101]',  0.77,'vessel',       2.509,  2.187, '2026-03-20T06:21:00Z','S1A_IW_GRDH_20260320T062143_001', false, false),
    ('patch_0014','patch_0014','[122,178,196,244]','[122,178,196,244]',0.76,'vessel',       4.123,  0.834, '2026-03-21T05:05:00Z','S1A_IW_GRDH_20260321T050500_009', false, false),
    ('patch_0015','patch_0015','[55,99,129,165]',  '[55,99,129,165]',  0.74,'large_vessel', 4.882,  1.562, '2026-03-22T07:38:00Z','S1A_IW_GRDH_20260322T073800_010', false, false),
    -- Near Ghana/Accra approaches (5.5N, -0.2E)
    ('patch_0016','patch_0016','[188,74,262,138]', '[188,74,262,138]', 0.91,'vessel',       5.489, -0.173, '2026-03-23T04:55:00Z','S1A_IW_GRDH_20260323T045500_011', false, false),
    ('patch_0017','patch_0017','[101,155,175,219]','[101,155,175,219]',0.90,'large_vessel', 5.512, -0.198, '2026-03-23T04:55:00Z','S1A_IW_GRDH_20260323T045500_011', false, false),
    ('patch_0018','patch_0018','[222,118,296,184]','[222,118,296,184]',0.88,'vessel',       5.478, -0.145, '2026-03-25T06:40:00Z','S1A_IW_GRDH_20260325T064000_012', false, false),
    -- Near Abidjan/Ivory Coast (5.3N, -4.0E — outside lon range, use -1.8 instead)
    ('patch_0019','patch_0019','[44,188,118,254]', '[44,188,118,254]', 0.87,'vessel',       5.301, -1.782, '2026-03-26T03:28:00Z','S1A_IW_GRDH_20260326T032800_013', false, false),
    ('patch_0020','patch_0020','[133,55,207,119]', '[133,55,207,119]', 0.85,'vessel',       5.267, -1.809, '2026-03-26T03:28:00Z','S1A_IW_GRDH_20260326T032800_013', false, false),
    -- Port Harcourt/Niger Delta approaches (4.7N, 7.0E)
    -- Three dark vessels detected at high confidence in this hotspot
    ('patch_0021','patch_0021','[77,132,151,198]', '[77,132,151,198]', 0.94,'dark_vessel',  4.688,  6.983, '2026-03-27T07:14:00Z','S1A_IW_GRDH_20260327T071400_014', false, true),
    ('patch_0022','patch_0022','[200,88,274,154]', '[200,88,274,154]', 0.92,'vessel',       4.712,  7.021, '2026-03-27T07:14:00Z','S1A_IW_GRDH_20260327T071400_014', false, false),
    ('patch_0023','patch_0023','[115,44,189,110]', '[115,44,189,110]', 0.90,'dark_vessel',  4.701,  6.958, '2026-03-29T08:02:00Z','S1A_IW_GRDH_20260329T080200_015', false, true),
    ('patch_0024','patch_0024','[38,165,112,231]', '[38,165,112,231]', 0.88,'vessel',       4.674,  7.044, '2026-03-29T08:02:00Z','S1A_IW_GRDH_20260329T080200_015', false, false),
    ('patch_0025','patch_0025','[177,201,251,267]','[177,201,251,267]',0.85,'dark_vessel',  4.659,  6.997, '2026-03-31T05:33:00Z','S1A_IW_GRDH_20260331T053300_016', false, true),
    -- Open mid-Gulf scatter continued
    ('patch_0026','patch_0026','[99,78,173,142]',  '[99,78,173,142]',  0.82,'vessel',       2.031,  3.198, '2026-04-01T09:20:00Z','S1A_IW_GRDH_20260401T092000_017', false, false),
    ('patch_0027','patch_0027','[211,133,285,199]','[211,133,285,199]',0.80,'vessel',       1.403,  5.044, '2026-04-02T04:48:00Z','S1A_IW_GRDH_20260402T044800_018', false, false),
    ('patch_0028','patch_0028','[66,200,140,266]', '[66,200,140,266]', 0.78,'vessel',       3.788,  1.677, '2026-04-03T06:09:00Z','S1A_IW_GRDH_20260403T060900_019', false, false),
    ('patch_0029','patch_0029','[144,55,218,121]', '[144,55,218,121]', 0.76,'vessel',      -1.044,  4.322, '2026-04-04T07:31:00Z','S1A_IW_GRDH_20260404T073100_020', false, false),
    ('patch_0030','patch_0030','[33,111,107,177]', '[33,111,107,177]', 0.72,'vessel',       0.287,  2.814, '2026-04-05T05:55:00Z','S1A_IW_GRDH_20260405T055500_021', false, false),

    -- ---- MEDIUM CONFIDENCE ~0.45-0.70 (rows 31-43) ----------------------
    -- is_dark=true, confidence sufficient — not flagged (above 0.45 threshold)
    ('patch_0031','patch_0031','[102,85,178,143]', '[102,85,178,143]', 0.68,'dark_vessel',  1.923,  5.634, '2026-03-10T02:18:00Z','S1A_IW_GRDH_20260310T021800_022', false, true),
    ('patch_0032','patch_0032','[231,140,307,208]','[231,140,307,208]',0.65,'dark_vessel',  2.774,  6.102, '2026-03-12T03:44:00Z','S1A_IW_GRDH_20260312T034400_023', false, true),
    ('patch_0033','patch_0033','[88,197,162,263]', '[88,197,162,263]', 0.62,'dark_vessel',  0.512,  7.018, '2026-03-15T08:30:00Z','S1A_IW_GRDH_20260315T083000_024', false, true),
    ('patch_0034','patch_0034','[166,62,240,128]', '[166,62,240,128]', 0.60,'dark_vessel', -0.889,  3.777, '2026-03-18T05:22:00Z','S1A_IW_GRDH_20260318T052200_025', false, true),
    ('patch_0035','patch_0035','[44,118,118,184]', '[44,118,118,184]', 0.58,'dark_vessel',  3.041,  4.519, '2026-03-22T09:07:00Z','S1A_IW_GRDH_20260322T090700_026', false, true),
    ('patch_0036','patch_0036','[122,33,196,99]',  '[122,33,196,99]',  0.56,'dark_vessel',  4.388,  5.883, '2026-03-25T04:14:00Z','S1A_IW_GRDH_20260325T041400_027', false, true),
    ('patch_0037','patch_0037','[200,175,274,241]','[200,175,274,241]',0.53,'dark_vessel',  1.112,  6.741, '2026-03-28T06:55:00Z','S1A_IW_GRDH_20260328T065500_028', false, true),
    ('patch_0038','patch_0038','[77,90,151,156]',  '[77,90,151,156]',  0.51,'dark_vessel', -1.534,  5.298, '2026-04-01T03:40:00Z','S1A_IW_GRDH_20260401T034000_029', false, true),
    -- Non-dark medium confidence
    ('patch_0039','patch_0039','[155,210,229,276]','[155,210,229,276]',0.67,'vessel',       2.312,  1.034, '2026-03-17T04:19:00Z','S1A_IW_GRDH_20260317T041900_030', false, false),
    ('patch_0040','patch_0040','[33,45,107,111]',  '[33,45,107,111]',  0.63,'vessel',       4.011, -0.672, '2026-03-20T07:55:00Z','S1A_IW_GRDH_20260320T062143_001', false, false),
    ('patch_0041','patch_0041','[188,133,262,199]','[188,133,262,199]',0.59,'vessel',       5.723,  0.291, '2026-03-24T06:03:00Z','S1A_IW_GRDH_20260324T060300_031', false, false),
    ('patch_0042','patch_0042','[111,66,185,132]', '[111,66,185,132]', 0.55,'vessel',       3.607,  2.748, '2026-03-30T08:48:00Z','S1A_IW_GRDH_20260330T084800_032', false, false),
    ('patch_0043','patch_0043','[222,188,296,254]','[222,188,296,254]',0.48,'vessel',      -0.391,  1.563, '2026-04-03T05:17:00Z','S1A_IW_GRDH_20260403T051700_033', true,  false),

    -- ---- LOW CONFIDENCE ~0.30-0.45 (rows 44-50) -------------------------
    -- All 7 rows are flagged_for_review=true (confidence < 0.45 threshold);
    -- 4 of them are also is_dark=true — brings total is_dark to 8+4+3=15
    ('patch_0044','patch_0044','[55,154,129,220]', '[55,154,129,220]', 0.44,'dark_vessel',  4.498,  3.312, '2026-03-13T09:33:00Z','S1A_IW_GRDH_20260313T093300_034', true,  true),
    ('patch_0045','patch_0045','[144,77,218,143]', '[144,77,218,143]', 0.42,'vessel',       1.756,  7.234, '2026-03-19T04:05:00Z','S1A_IW_GRDH_20260319T040500_035', true,  false),
    ('patch_0046','patch_0046','[88,210,162,276]', '[88,210,162,276]', 0.40,'dark_vessel',  3.187,  5.098, '2026-03-24T08:20:00Z','S1A_IW_GRDH_20260324T082000_036', true,  true),
    ('patch_0047','patch_0047','[211,55,285,121]', '[211,55,285,121]', 0.38,'vessel',      -0.742,  6.489, '2026-03-28T03:12:00Z','S1A_IW_GRDH_20260328T031200_037', true,  false),
    ('patch_0048','patch_0048','[33,132,107,198]', '[33,132,107,198]', 0.36,'dark_vessel',  2.834,  0.187, '2026-04-01T07:58:00Z','S1A_IW_GRDH_20260401T075800_038', true,  true),
    ('patch_0049','patch_0049','[166,88,240,154]', '[166,88,240,154]', 0.33,'vessel',       4.914,  4.672, '2026-04-04T04:44:00Z','S1A_IW_GRDH_20260404T044400_039', true,  false),
    ('patch_0050','patch_0050','[99,165,173,231]', '[99,165,173,231]', 0.31,'dark_vessel',  1.234,  2.509, '2026-04-07T06:29:00Z','S1A_IW_GRDH_20260407T062900_040', true,  true)
) AS v(
    patch_id, tile_id, bbox_xyxy, pixel_coords, confidence, class_label,
    lat, lon, ts, scene_id, flagged_for_review, is_dark
)
WHERE NOT EXISTS (SELECT 1 FROM detection_records LIMIT 1);

-- ---------------------------------------------------------------------------
-- model_metrics  (5 rows — mAP50 progression, inserted only if table empty)
-- ---------------------------------------------------------------------------
INSERT INTO model_metrics (model_name, map50, evaluated_at, notes)
SELECT v.model_name, v.map50, v.evaluated_at::timestamptz, v.notes
FROM (VALUES
    ('yolov8n-darkwater', 0.61, '2026-02-07T10:00:00Z', 'Baseline run on initial 500-image dataset.'),
    ('yolov8n-darkwater', 0.64, '2026-02-21T10:00:00Z', 'Added 150 active-learning labels from Label Studio round 1.'),
    ('yolov8n-darkwater', 0.68, '2026-03-07T10:00:00Z', 'Augmentation: random speckle noise + flip. Round 2 labels merged.'),
    ('yolov8n-darkwater', 0.71, '2026-03-22T10:00:00Z', 'Lee filter pre-processing applied; coastline masking improved.'),
    ('yolov8n-darkwater', 0.74, '2026-04-05T10:00:00Z', 'Round 3 labels (+200 dark_vessel patches). Promoted to production.')
) AS v(model_name, map50, evaluated_at, notes)
WHERE NOT EXISTS (SELECT 1 FROM model_metrics LIMIT 1);

COMMIT;
