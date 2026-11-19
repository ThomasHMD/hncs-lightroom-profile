#!/usr/bin/env python3
"""Chaîne de rendu Adobe (Camera Raw / Lightroom) pour un profil DCP, en numpy.

Reproduit le rendu de référence du SDK DNG d'Adobe (dng_render.cpp,
dng_reference.cpp, dng_color_spec.cpp, dng_camera_profile.cpp, dng_spline.cpp,
dng_hue_sat_map.cpp ; lus dans le miroir AOSP external/dng_sdk, branche
android-7.1.1_r31) et de la spec DNG 1.7, pour pouvoir ajuster les tables d'un
profil hors de Lightroom.  dcamprof 1.0.6 (dngref.c) sert de contrôle croisé
dans --self-test.

Chaîne, dans l'ordre du SDK (dng_render_task::ProcessArea) :
  1. RGB caméra -> écrêtage au blanc caméra -> matrice caméra->XYZ D50
     (ForwardMatrix ou ColorMatrix + Bradford, interpolée entre les deux
     illuminants en 1/T d'après la balance) -> ProPhoto linéaire borné [0,1]
  2. HueSatMap (HSV, avant exposition), carte interpolée entre illuminants
  3. rampe d'exposition (positive : échelle 2^e ; noir optionnel)
  4. LookTable (HSV, après exposition)
  5. courbe de tonalité RefBaselineRGBTone : (exposition négative) o (courbe du
     profil, spline Adobe ; à défaut courbe ACR3 par défaut), appliquée au
     max et au min, le canal intermédiaire interpolé
  6. sortie : ProPhoto linéaire ; ou XYZ D50 ; ou sRGB 8 bits.

Entrées : cam_rgb = RGB caméra linéaire (noir soustrait, saturation = 1),
wb_neutral = CameraNeutral / AsShotNeutral (RGB caméra du blanc).

    python3 chaine_adobe.py --self-test
    python3 chaine_adobe.py --dcp profil.dcp --cam 0.2,0.3,0.1 --wb 0.5,1,0.62
"""
import dataclasses
import importlib.util
import math
import pathlib
import sys

import numpy as np

# ---------------------------------------------------------------- constantes

# D50 (PCS) : dng_xy_coord.cpp PCStoXY = D50_xy_coord (0.3457, 0.3585).
D50_XY = (0.3457, 0.3585)
D50_XYZ = np.array([D50_XY[0] / D50_XY[1], 1.0, (1 - D50_XY[0] - D50_XY[1]) / D50_XY[1]])

# dng_color_space.cpp : dng_space_ProPhoto / dng_space_sRGB (matrices vers PCS,
# 4 chiffres, telles que dans le SDK).
PROPHOTO_VERS_XYZ_SDK = np.array([[0.7977, 0.1352, 0.0313],
                                  [0.2880, 0.7119, 0.0001],
                                  [0.0000, 0.0000, 0.8249]])
# Valeurs ICC précises (ROMM, D50), celles de dcamprof dngref.h.
PROPHOTO_VERS_XYZ_ICC = np.linalg.inv(np.array([[+1.3457530096, -0.2556031200, -0.0510246682],
                                                [-0.5444259963, +1.5080962194, +0.0204718467],
                                                [+0.0000000000, +0.0000000000, +1.2119675456]]))
SRGB_VERS_XYZ_D50 = np.array([[0.4361, 0.3851, 0.1431],
                              [0.2225, 0.7169, 0.0606],
                              [0.0139, 0.0971, 0.7141]])

BRADFORD = np.array([[0.8951, 0.2664, -0.1614],
                     [-0.7502, 1.7135, 0.0367],
                     [0.0389, -0.0685, 1.0296]])

# dng_camera_profile.cpp IlluminantToTemperature (codes EXIF LightSource).
_TEMP_ECLAIRAGE = {17: 2850.0, 3: 2850.0, 24: 3200.0, 23: 5000.0,
                   20: 5500.0, 1: 5500.0, 9: 5500.0, 4: 5500.0, 18: 5500.0,
                   21: 6500.0, 19: 6500.0, 10: 6500.0, 22: 7500.0, 11: 7500.0,
                   12: (5700.0 + 7100.0) * 0.5, 13: (4600.0 + 5500.0) * 0.5,
                   14: (3800.0 + 4500.0) * 0.5, 2: (3800.0 + 4500.0) * 0.5,
                   15: (3250.0 + 3800.0) * 0.5, 16: (2600.0 + 3250.0) * 0.5}

# dng_temperature.cpp (Wyszecki & Stiles p.228) : r(=1e6/T), u, v, pente t.
_TINT_SCALE = -3000.0
_TABLE_TEMP = np.array([
    (0, 0.18006, 0.26352, -0.24341), (10, 0.18066, 0.26589, -0.25479),
    (20, 0.18133, 0.26846, -0.26876), (30, 0.18208, 0.27119, -0.28539),
    (40, 0.18293, 0.27407, -0.30470), (50, 0.18388, 0.27709, -0.32675),
    (60, 0.18494, 0.28021, -0.35156), (70, 0.18611, 0.28342, -0.37915),
    (80, 0.18740, 0.28668, -0.40955), (90, 0.18880, 0.28997, -0.44278),
    (100, 0.19032, 0.29326, -0.47888), (125, 0.19462, 0.30141, -0.58204),
    (150, 0.19962, 0.30921, -0.70471), (175, 0.20525, 0.31647, -0.84901),
    (200, 0.21142, 0.32312, -1.0182), (225, 0.21807, 0.32909, -1.2168),
    (250, 0.22511, 0.33439, -1.4512), (275, 0.23247, 0.33904, -1.7298),
    (300, 0.24010, 0.34308, -2.0637), (325, 0.24702, 0.34655, -2.4681),
    (350, 0.25591, 0.34951, -2.9641), (375, 0.26400, 0.35200, -3.5814),
    (400, 0.27218, 0.35407, -4.3633), (425, 0.28039, 0.35577, -5.3762),
    (450, 0.28863, 0.35714, -6.7262), (475, 0.29685, 0.35823, -8.5955),
    (500, 0.30505, 0.35907, -11.324), (525, 0.31320, 0.35968, -15.628),
    (550, 0.32129, 0.36011, -23.325), (575, 0.32931, 0.36038, -40.770),
    (600, 0.33724, 0.36051, -116.45)])

# dng_render.cpp dng_tone_curve_acr3_default : table de 1025 valeurs, interpolation
# linéaire.  Identique à dcamprof dngref.c dcp_acr_tonecurve().
ACR3 = np.array([
    0.00000, 0.00078, 0.00160, 0.00242, 0.00314, 0.00385, 0.00460, 0.00539,
    0.00623, 0.00712, 0.00806, 0.00906, 0.01012, 0.01122, 0.01238, 0.01359,
    0.01485, 0.01616, 0.01751, 0.01890, 0.02033, 0.02180, 0.02331, 0.02485,
    0.02643, 0.02804, 0.02967, 0.03134, 0.03303, 0.03475, 0.03648, 0.03824,
    0.04002, 0.04181, 0.04362, 0.04545, 0.04730, 0.04916, 0.05103, 0.05292,
    0.05483, 0.05675, 0.05868, 0.06063, 0.06259, 0.06457, 0.06655, 0.06856,
    0.07057, 0.07259, 0.07463, 0.07668, 0.07874, 0.08081, 0.08290, 0.08499,
    0.08710, 0.08921, 0.09134, 0.09348, 0.09563, 0.09779, 0.09996, 0.10214,
    0.10433, 0.10652, 0.10873, 0.11095, 0.11318, 0.11541, 0.11766, 0.11991,
    0.12218, 0.12445, 0.12673, 0.12902, 0.13132, 0.13363, 0.13595, 0.13827,
    0.14061, 0.14295, 0.14530, 0.14765, 0.15002, 0.15239, 0.15477, 0.15716,
    0.15956, 0.16197, 0.16438, 0.16680, 0.16923, 0.17166, 0.17410, 0.17655,
    0.17901, 0.18148, 0.18395, 0.18643, 0.18891, 0.19141, 0.19391, 0.19641,
    0.19893, 0.20145, 0.20398, 0.20651, 0.20905, 0.21160, 0.21416, 0.21672,
    0.21929, 0.22185, 0.22440, 0.22696, 0.22950, 0.23204, 0.23458, 0.23711,
    0.23963, 0.24215, 0.24466, 0.24717, 0.24967, 0.25216, 0.25465, 0.25713,
    0.25961, 0.26208, 0.26454, 0.26700, 0.26945, 0.27189, 0.27433, 0.27676,
    0.27918, 0.28160, 0.28401, 0.28641, 0.28881, 0.29120, 0.29358, 0.29596,
    0.29833, 0.30069, 0.30305, 0.30540, 0.30774, 0.31008, 0.31241, 0.31473,
    0.31704, 0.31935, 0.32165, 0.32395, 0.32623, 0.32851, 0.33079, 0.33305,
    0.33531, 0.33756, 0.33981, 0.34205, 0.34428, 0.34650, 0.34872, 0.35093,
    0.35313, 0.35532, 0.35751, 0.35969, 0.36187, 0.36404, 0.36620, 0.36835,
    0.37050, 0.37264, 0.37477, 0.37689, 0.37901, 0.38112, 0.38323, 0.38533,
    0.38742, 0.38950, 0.39158, 0.39365, 0.39571, 0.39777, 0.39982, 0.40186,
    0.40389, 0.40592, 0.40794, 0.40996, 0.41197, 0.41397, 0.41596, 0.41795,
    0.41993, 0.42191, 0.42388, 0.42584, 0.42779, 0.42974, 0.43168, 0.43362,
    0.43554, 0.43747, 0.43938, 0.44129, 0.44319, 0.44509, 0.44698, 0.44886,
    0.45073, 0.45260, 0.45447, 0.45632, 0.45817, 0.46002, 0.46186, 0.46369,
    0.46551, 0.46733, 0.46914, 0.47095, 0.47275, 0.47454, 0.47633, 0.47811,
    0.47989, 0.48166, 0.48342, 0.48518, 0.48693, 0.48867, 0.49041, 0.49214,
    0.49387, 0.49559, 0.49730, 0.49901, 0.50072, 0.50241, 0.50410, 0.50579,
    0.50747, 0.50914, 0.51081, 0.51247, 0.51413, 0.51578, 0.51742, 0.51906,
    0.52069, 0.52232, 0.52394, 0.52556, 0.52717, 0.52878, 0.53038, 0.53197,
    0.53356, 0.53514, 0.53672, 0.53829, 0.53986, 0.54142, 0.54297, 0.54452,
    0.54607, 0.54761, 0.54914, 0.55067, 0.55220, 0.55371, 0.55523, 0.55673,
    0.55824, 0.55973, 0.56123, 0.56271, 0.56420, 0.56567, 0.56715, 0.56861,
    0.57007, 0.57153, 0.57298, 0.57443, 0.57587, 0.57731, 0.57874, 0.58017,
    0.58159, 0.58301, 0.58443, 0.58583, 0.58724, 0.58864, 0.59003, 0.59142,
    0.59281, 0.59419, 0.59556, 0.59694, 0.59830, 0.59966, 0.60102, 0.60238,
    0.60373, 0.60507, 0.60641, 0.60775, 0.60908, 0.61040, 0.61173, 0.61305,
    0.61436, 0.61567, 0.61698, 0.61828, 0.61957, 0.62087, 0.62216, 0.62344,
    0.62472, 0.62600, 0.62727, 0.62854, 0.62980, 0.63106, 0.63232, 0.63357,
    0.63482, 0.63606, 0.63730, 0.63854, 0.63977, 0.64100, 0.64222, 0.64344,
    0.64466, 0.64587, 0.64708, 0.64829, 0.64949, 0.65069, 0.65188, 0.65307,
    0.65426, 0.65544, 0.65662, 0.65779, 0.65897, 0.66013, 0.66130, 0.66246,
    0.66362, 0.66477, 0.66592, 0.66707, 0.66821, 0.66935, 0.67048, 0.67162,
    0.67275, 0.67387, 0.67499, 0.67611, 0.67723, 0.67834, 0.67945, 0.68055,
    0.68165, 0.68275, 0.68385, 0.68494, 0.68603, 0.68711, 0.68819, 0.68927,
    0.69035, 0.69142, 0.69249, 0.69355, 0.69461, 0.69567, 0.69673, 0.69778,
    0.69883, 0.69988, 0.70092, 0.70196, 0.70300, 0.70403, 0.70506, 0.70609,
    0.70711, 0.70813, 0.70915, 0.71017, 0.71118, 0.71219, 0.71319, 0.71420,
    0.71520, 0.71620, 0.71719, 0.71818, 0.71917, 0.72016, 0.72114, 0.72212,
    0.72309, 0.72407, 0.72504, 0.72601, 0.72697, 0.72794, 0.72890, 0.72985,
    0.73081, 0.73176, 0.73271, 0.73365, 0.73460, 0.73554, 0.73647, 0.73741,
    0.73834, 0.73927, 0.74020, 0.74112, 0.74204, 0.74296, 0.74388, 0.74479,
    0.74570, 0.74661, 0.74751, 0.74842, 0.74932, 0.75021, 0.75111, 0.75200,
    0.75289, 0.75378, 0.75466, 0.75555, 0.75643, 0.75730, 0.75818, 0.75905,
    0.75992, 0.76079, 0.76165, 0.76251, 0.76337, 0.76423, 0.76508, 0.76594,
    0.76679, 0.76763, 0.76848, 0.76932, 0.77016, 0.77100, 0.77183, 0.77267,
    0.77350, 0.77432, 0.77515, 0.77597, 0.77680, 0.77761, 0.77843, 0.77924,
    0.78006, 0.78087, 0.78167, 0.78248, 0.78328, 0.78408, 0.78488, 0.78568,
    0.78647, 0.78726, 0.78805, 0.78884, 0.78962, 0.79040, 0.79118, 0.79196,
    0.79274, 0.79351, 0.79428, 0.79505, 0.79582, 0.79658, 0.79735, 0.79811,
    0.79887, 0.79962, 0.80038, 0.80113, 0.80188, 0.80263, 0.80337, 0.80412,
    0.80486, 0.80560, 0.80634, 0.80707, 0.80780, 0.80854, 0.80926, 0.80999,
    0.81072, 0.81144, 0.81216, 0.81288, 0.81360, 0.81431, 0.81503, 0.81574,
    0.81645, 0.81715, 0.81786, 0.81856, 0.81926, 0.81996, 0.82066, 0.82135,
    0.82205, 0.82274, 0.82343, 0.82412, 0.82480, 0.82549, 0.82617, 0.82685,
    0.82753, 0.82820, 0.82888, 0.82955, 0.83022, 0.83089, 0.83155, 0.83222,
    0.83288, 0.83354, 0.83420, 0.83486, 0.83552, 0.83617, 0.83682, 0.83747,
    0.83812, 0.83877, 0.83941, 0.84005, 0.84069, 0.84133, 0.84197, 0.84261,
    0.84324, 0.84387, 0.84450, 0.84513, 0.84576, 0.84639, 0.84701, 0.84763,
    0.84825, 0.84887, 0.84949, 0.85010, 0.85071, 0.85132, 0.85193, 0.85254,
    0.85315, 0.85375, 0.85436, 0.85496, 0.85556, 0.85615, 0.85675, 0.85735,
    0.85794, 0.85853, 0.85912, 0.85971, 0.86029, 0.86088, 0.86146, 0.86204,
    0.86262, 0.86320, 0.86378, 0.86435, 0.86493, 0.86550, 0.86607, 0.86664,
    0.86720, 0.86777, 0.86833, 0.86889, 0.86945, 0.87001, 0.87057, 0.87113,
    0.87168, 0.87223, 0.87278, 0.87333, 0.87388, 0.87443, 0.87497, 0.87552,
    0.87606, 0.87660, 0.87714, 0.87768, 0.87821, 0.87875, 0.87928, 0.87981,
    0.88034, 0.88087, 0.88140, 0.88192, 0.88244, 0.88297, 0.88349, 0.88401,
    0.88453, 0.88504, 0.88556, 0.88607, 0.88658, 0.88709, 0.88760, 0.88811,
    0.88862, 0.88912, 0.88963, 0.89013, 0.89063, 0.89113, 0.89163, 0.89212,
    0.89262, 0.89311, 0.89360, 0.89409, 0.89458, 0.89507, 0.89556, 0.89604,
    0.89653, 0.89701, 0.89749, 0.89797, 0.89845, 0.89892, 0.89940, 0.89987,
    0.90035, 0.90082, 0.90129, 0.90176, 0.90222, 0.90269, 0.90316, 0.90362,
    0.90408, 0.90454, 0.90500, 0.90546, 0.90592, 0.90637, 0.90683, 0.90728,
    0.90773, 0.90818, 0.90863, 0.90908, 0.90952, 0.90997, 0.91041, 0.91085,
    0.91130, 0.91173, 0.91217, 0.91261, 0.91305, 0.91348, 0.91392, 0.91435,
    0.91478, 0.91521, 0.91564, 0.91606, 0.91649, 0.91691, 0.91734, 0.91776,
    0.91818, 0.91860, 0.91902, 0.91944, 0.91985, 0.92027, 0.92068, 0.92109,
    0.92150, 0.92191, 0.92232, 0.92273, 0.92314, 0.92354, 0.92395, 0.92435,
    0.92475, 0.92515, 0.92555, 0.92595, 0.92634, 0.92674, 0.92713, 0.92753,
    0.92792, 0.92831, 0.92870, 0.92909, 0.92947, 0.92986, 0.93025, 0.93063,
    0.93101, 0.93139, 0.93177, 0.93215, 0.93253, 0.93291, 0.93328, 0.93366,
    0.93403, 0.93440, 0.93478, 0.93515, 0.93551, 0.93588, 0.93625, 0.93661,
    0.93698, 0.93734, 0.93770, 0.93807, 0.93843, 0.93878, 0.93914, 0.93950,
    0.93986, 0.94021, 0.94056, 0.94092, 0.94127, 0.94162, 0.94197, 0.94231,
    0.94266, 0.94301, 0.94335, 0.94369, 0.94404, 0.94438, 0.94472, 0.94506,
    0.94540, 0.94573, 0.94607, 0.94641, 0.94674, 0.94707, 0.94740, 0.94774,
    0.94807, 0.94839, 0.94872, 0.94905, 0.94937, 0.94970, 0.95002, 0.95035,
    0.95067, 0.95099, 0.95131, 0.95163, 0.95194, 0.95226, 0.95257, 0.95289,
    0.95320, 0.95351, 0.95383, 0.95414, 0.95445, 0.95475, 0.95506, 0.95537,
    0.95567, 0.95598, 0.95628, 0.95658, 0.95688, 0.95718, 0.95748, 0.95778,
    0.95808, 0.95838, 0.95867, 0.95897, 0.95926, 0.95955, 0.95984, 0.96013,
    0.96042, 0.96071, 0.96100, 0.96129, 0.96157, 0.96186, 0.96214, 0.96242,
    0.96271, 0.96299, 0.96327, 0.96355, 0.96382, 0.96410, 0.96438, 0.96465,
    0.96493, 0.96520, 0.96547, 0.96574, 0.96602, 0.96629, 0.96655, 0.96682,
    0.96709, 0.96735, 0.96762, 0.96788, 0.96815, 0.96841, 0.96867, 0.96893,
    0.96919, 0.96945, 0.96971, 0.96996, 0.97022, 0.97047, 0.97073, 0.97098,
    0.97123, 0.97149, 0.97174, 0.97199, 0.97223, 0.97248, 0.97273, 0.97297,
    0.97322, 0.97346, 0.97371, 0.97395, 0.97419, 0.97443, 0.97467, 0.97491,
    0.97515, 0.97539, 0.97562, 0.97586, 0.97609, 0.97633, 0.97656, 0.97679,
    0.97702, 0.97725, 0.97748, 0.97771, 0.97794, 0.97817, 0.97839, 0.97862,
    0.97884, 0.97907, 0.97929, 0.97951, 0.97973, 0.97995, 0.98017, 0.98039,
    0.98061, 0.98082, 0.98104, 0.98125, 0.98147, 0.98168, 0.98189, 0.98211,
    0.98232, 0.98253, 0.98274, 0.98295, 0.98315, 0.98336, 0.98357, 0.98377,
    0.98398, 0.98418, 0.98438, 0.98458, 0.98478, 0.98498, 0.98518, 0.98538,
    0.98558, 0.98578, 0.98597, 0.98617, 0.98636, 0.98656, 0.98675, 0.98694,
    0.98714, 0.98733, 0.98752, 0.98771, 0.98789, 0.98808, 0.98827, 0.98845,
    0.98864, 0.98882, 0.98901, 0.98919, 0.98937, 0.98955, 0.98973, 0.98991,
    0.99009, 0.99027, 0.99045, 0.99063, 0.99080, 0.99098, 0.99115, 0.99133,
    0.99150, 0.99167, 0.99184, 0.99201, 0.99218, 0.99235, 0.99252, 0.99269,
    0.99285, 0.99302, 0.99319, 0.99335, 0.99351, 0.99368, 0.99384, 0.99400,
    0.99416, 0.99432, 0.99448, 0.99464, 0.99480, 0.99495, 0.99511, 0.99527,
    0.99542, 0.99558, 0.99573, 0.99588, 0.99603, 0.99619, 0.99634, 0.99649,
    0.99664, 0.99678, 0.99693, 0.99708, 0.99722, 0.99737, 0.99751, 0.99766,
    0.99780, 0.99794, 0.99809, 0.99823, 0.99837, 0.99851, 0.99865, 0.99879,
    0.99892, 0.99906, 0.99920, 0.99933, 0.99947, 0.99960, 0.99974, 0.99987,
    1.00000,
])


# ------------------------------------------------------- température / xy

def xy_vers_temp(xy):
    """dng_temperature::Set_xy_coord (= dcamprof dcp_xy2temp). -> (T kelvin, tint)."""
    x, y = xy
    u = 2.0 * x / (1.5 - x + 6.0 * y)
    v = 3.0 * y / (1.5 - x + 6.0 * y)
    last_dt = last_du = last_dv = 0.0
    for i in range(1, 31):
        du = 1.0
        dv = _TABLE_TEMP[i, 3]
        ln = math.sqrt(1.0 + dv * dv)
        du /= ln
        dv /= ln
        uu = u - _TABLE_TEMP[i, 1]
        vv = v - _TABLE_TEMP[i, 2]
        dt = -uu * dv + vv * du
        if dt <= 0.0 or i == 30:
            if dt > 0.0:
                dt = 0.0
            dt = -dt
            f = 0.0 if i == 1 else dt / (last_dt + dt)
            temp = 1.0e6 / (_TABLE_TEMP[i - 1, 0] * f + _TABLE_TEMP[i, 0] * (1.0 - f))
            uu = u - (_TABLE_TEMP[i - 1, 1] * f + _TABLE_TEMP[i, 1] * (1.0 - f))
            vv = v - (_TABLE_TEMP[i - 1, 2] * f + _TABLE_TEMP[i, 2] * (1.0 - f))
            du = du * (1.0 - f) + last_du * f
            dv = dv * (1.0 - f) + last_dv * f
            ln = math.sqrt(du * du + dv * dv)
            du /= ln
            dv /= ln
            return temp, (uu * du + vv * dv) * _TINT_SCALE
        last_dt, last_du, last_dv = dt, du, dv
    return 0.0, 0.0


def temp_vers_xy(temp, tint=0.0):
    """dng_temperature::Get_xy_coord (= dcamprof dcp_temp2xy)."""
    r = 1.0e6 / temp
    offset = tint * (1.0 / _TINT_SCALE)
    for i in range(0, 30):
        if r < _TABLE_TEMP[i + 1, 0] or i == 29:
            f = (_TABLE_TEMP[i + 1, 0] - r) / (_TABLE_TEMP[i + 1, 0] - _TABLE_TEMP[i, 0])
            u = _TABLE_TEMP[i, 1] * f + _TABLE_TEMP[i + 1, 1] * (1.0 - f)
            v = _TABLE_TEMP[i, 2] * f + _TABLE_TEMP[i + 1, 2] * (1.0 - f)
            uu1, vv1 = 1.0, _TABLE_TEMP[i, 3]
            uu2, vv2 = 1.0, _TABLE_TEMP[i + 1, 3]
            l1, l2 = math.sqrt(1 + vv1 * vv1), math.sqrt(1 + vv2 * vv2)
            uu1, vv1, uu2, vv2 = uu1 / l1, vv1 / l1, uu2 / l2, vv2 / l2
            uu3 = uu1 * f + uu2 * (1.0 - f)
            vv3 = vv1 * f + vv2 * (1.0 - f)
            l3 = math.hypot(uu3, vv3)
            u += uu3 / l3 * offset
            v += vv3 / l3 * offset
            d = u - 4.0 * v + 2.0
            return (1.5 * u / d, v / d)


def xy_vers_xyz(xy):
    """dng_xy_coord.cpp XYtoXYZ (Y=1, xy borné comme dans le SDK)."""
    x = min(max(xy[0], 0.000001), 0.999999)
    y = min(max(xy[1], 0.000001), 0.999999)
    if x + y > 0.999999:
        k = 0.999999 / (x + y)
        x, y = x * k, y * k
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def _xyz_vers_xy(xyz):
    t = float(np.sum(xyz))
    return (xyz[0] / t, xyz[1] / t) if t > 0 else D50_XY


def _map_white(xy1, xy2):
    """dng_color_spec.cpp MapWhiteMatrix : adaptation Bradford linéaire xy1 -> xy2."""
    w1 = np.maximum(BRADFORD @ xy_vers_xyz(xy1), 0.0)
    w2 = np.maximum(BRADFORD @ xy_vers_xyz(xy2), 0.0)
    a = np.diag([min(max(w2[i] / w1[i] if w1[i] > 0 else 10.0, 0.1), 10.0) for i in range(3)])
    return np.linalg.inv(BRADFORD) @ a @ BRADFORD


# ------------------------------------------------------------------ profil

@dataclasses.dataclass
class Profil:
    """Contenu utile d'un DCP (matrices 3x3 en lignes, tables en (V,H,S,3))."""
    cm1: np.ndarray
    cm2: np.ndarray = None
    fm1: np.ndarray = None
    fm2: np.ndarray = None
    ill1: int = 0
    ill2: int = 0
    hsm1: np.ndarray = None          # (V,H,S,3) : décalage teinte (deg), échelle sat, échelle val
    hsm2: np.ndarray = None
    hsm_encodage: int = 0            # 0 linéaire, 1 sRGB
    look: np.ndarray = None
    look_encodage: int = 0
    courbe: np.ndarray = None        # points (x,y) ProfileToneCurve ; None = ACR3 par défaut
    exposition_base_profil: float = 0.0   # BaselineExposureOffset (tag 51109)
    noir_defaut_aucun: bool = False  # DefaultBlackRender == None (tag 51110 == 1)
    nom: str = ""


def _m3(v):
    return None if v is None else np.asarray(v, float).reshape(3, 3)


def _table(dims, data):
    if data is None or dims is None:
        return None
    h, s, v = [int(x) for x in dims]
    a = np.asarray(data, float)
    if a.size != h * s * v * 3:
        raise ValueError("table HSM/Look : %d valeurs, %dx%dx%d attendu" % (a.size, h, s, v))
    return a.reshape(v, h, s, 3)


def charger_dcp_dict(d):
    """Construit un Profil depuis le dict de dcp.lire() (clés de tags inconnus : numéro)."""
    def un(k, defaut=None):
        v = d.get(k)
        if v is None:
            return defaut
        return v[0] if isinstance(v, list) else v
    cm1 = _m3(d.get("ColorMatrix1"))
    if cm1 is None:
        raise ValueError("DCP sans ColorMatrix1")
    c = d.get("ProfileToneCurve")
    courbe = np.asarray(c, float).reshape(-1, 2) if c else None
    p = Profil(cm1=cm1, cm2=_m3(d.get("ColorMatrix2")),
               fm1=_m3(d.get("ForwardMatrix1")), fm2=_m3(d.get("ForwardMatrix2")),
               ill1=int(un("CalibrationIlluminant1", 0)), ill2=int(un("CalibrationIlluminant2", 0)),
               hsm1=_table(d.get("ProfileHueSatMapDims"), d.get("ProfileHueSatMapData1")),
               hsm2=_table(d.get("ProfileHueSatMapDims"), d.get("ProfileHueSatMapData2")),
               hsm_encodage=int(un("ProfileHueSatMapEncoding", 0)),
               look=_table(d.get("ProfileLookTableDims"), d.get("ProfileLookTableData")),
               look_encodage=int(un("ProfileLookTableEncoding", 0)),
               courbe=courbe,
               exposition_base_profil=float(un("51109", un("BaselineExposureOffset", 0.0))),
               noir_defaut_aucun=int(un("51110", un("DefaultBlackRender", 0))) == 1,
               nom=str(d.get("ProfileName", "")))
    return p


def charger_dcp(chemin):
    """Lit un .dcp avec `dcp_ecrire.lire` (même dossier)."""
    import dcp_ecrire
    return charger_dcp_dict(dcp_ecrire.lire(str(chemin)))


# -------------------------------------------------- caméra -> XYZ D50 (étape 1)

def _normaliser_fm(m):
    """dng_camera_profile::NormalizeForwardMatrix : FM·(1,1,1) = blanc D50 exact."""
    if m is None:
        return None
    return np.diag(D50_XYZ) @ np.linalg.inv(np.diag(m @ np.ones(3))) @ m


def _normaliser_cm(m):
    """dng_camera_profile::NormalizeColorMatrix : max(CM·D50) ramené à 1 s'il sort de [0,99 ; 1,01]."""
    mx = float(np.max(m @ D50_XYZ))
    if mx > 0.0 and (mx < 0.99 or mx > 1.01):
        return m / mx
    return m


class SpecCouleur:
    """dng_color_spec : matrices interpolées d'un profil (ab = balance analogique
    diag, cc = CameraCalibration ; identité par défaut)."""

    def __init__(self, profil, ab=None, cc=None):
        p = profil
        self.ab = np.eye(3) if ab is None else np.diag(np.asarray(ab, float))
        self.cc = np.eye(3) if cc is None else np.asarray(cc, float).reshape(3, 3)
        t1 = _TEMP_ECLAIRAGE.get(p.ill1, 0.0)
        t2 = _TEMP_ECLAIRAGE.get(p.ill2, 0.0)
        cm1 = _normaliser_cm(p.cm1)
        fm1 = _normaliser_fm(p.fm1)
        self.inversion_hsm = False
        if p.cm2 is None or t1 <= 0 or t2 <= 0 or t1 == t2:
            self.t1 = self.t2 = 5000.0
            self.cm1 = self.cm2 = self.ab @ self.cc @ cm1
            self.fm1 = self.fm2 = fm1
        else:
            cm2 = _normaliser_cm(p.cm2)
            fm2 = _normaliser_fm(p.fm2)
            self.t1, self.t2 = t1, t2
            self.cm1, self.cm2 = self.ab @ self.cc @ cm1, self.ab @ self.cc @ cm2
            self.fm1, self.fm2 = fm1, fm2
            if t1 > t2:     # dng_color_spec : échange si températures dans le désordre
                self.t1, self.t2 = t2, t1
                self.cm1, self.cm2 = self.cm2, self.cm1
                self.fm1, self.fm2 = self.fm2, self.fm1
                self.inversion_hsm = True

    def poids(self, xy):
        """g : poids de l'illuminant 1 (interpolation linéaire en 1/T)."""
        t = xy_vers_temp(xy)[0]
        if t <= self.t1:
            return 1.0
        if t >= self.t2:
            return 0.0
        return (1.0 / t - 1.0 / self.t2) / (1.0 / self.t1 - 1.0 / self.t2)

    def xyz_vers_camera(self, xy):
        g = self.poids(xy)
        return g * self.cm1 + (1.0 - g) * self.cm2 if 0.0 < g < 1.0 else (self.cm1 if g >= 1 else self.cm2)

    def forward(self, xy):
        if self.fm1 is None and self.fm2 is None:
            return None
        g = self.poids(xy)
        if self.fm1 is not None and self.fm2 is not None:
            return self.fm1 if g >= 1 else self.fm2 if g <= 0 else g * self.fm1 + (1 - g) * self.fm2
        return self.fm1 if self.fm1 is not None else self.fm2

    def neutre_vers_xy(self, neutre):
        """dng_color_spec::NeutralToXY : itération température <-> xy (30 passes max)."""
        neutre = np.asarray(neutre, float)
        last = D50_XY
        for passe in range(30):
            nxt = _xyz_vers_xy(np.linalg.inv(self.xyz_vers_camera(last)) @ neutre)
            if abs(nxt[0] - last[0]) + abs(nxt[1] - last[1]) < 0.0000001:
                return nxt
            if passe == 29:
                nxt = ((last[0] + nxt[0]) * 0.5, (last[1] + nxt[1]) * 0.5)
            last = nxt
        return last

    def camera_vers_pcs(self, xy):
        """dng_color_spec::SetWhiteXY : (CameraToPCS, CameraWhite)."""
        cm = self.xyz_vers_camera(xy)
        blanc = cm @ xy_vers_xyz(xy)
        mx = float(np.max(blanc))
        blanc = np.clip(blanc / mx, 0.001, 1.0)
        fm = self.forward(xy)
        if fm is not None:
            ind_vers_ref = np.linalg.inv(self.ab @ self.cc)
            ref_blanc = ind_vers_ref @ blanc
            return fm @ np.linalg.inv(np.diag(ref_blanc)) @ ind_vers_ref, blanc
        # Sans ForwardMatrix : adaptation dans XYZ (Bradford), matrice mise à
        # l'échelle pour que le blanc PCS soit atteint quand le 1er canal sature.
        pcs_vers_cam = cm @ _map_white(D50_XY, xy)
        echelle = float(np.max(pcs_vers_cam @ D50_XYZ))
        return np.linalg.inv(pcs_vers_cam / echelle), blanc


# ------------------------------------------------------- HSV et tables (2, 4)

def rgb_vers_hsv(rgb):
    """DNG_RGBtoHSV (dng_utils.h) ; teinte en [0,6)."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    v = np.max(rgb, axis=-1)
    gap = v - np.min(rgb, axis=-1)
    ok = gap > 0
    sg = np.where(ok, gap, 1.0)
    sv = np.where(v > 0, v, 1.0)
    h = np.where(r == v, (g - b) / sg, np.where(g == v, 2.0 + (b - r) / sg, 4.0 + (r - g) / sg))
    h = np.where(h < 0, h + 6.0, h)
    h = np.where(ok, h, 0.0)
    s = np.where(ok, gap / sv, 0.0)
    return np.stack([h, s, v], axis=-1)


def hsv_vers_rgb(hsv):
    """DNG_HSVtoRGB (dng_utils.h)."""
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    h = np.mod(h, 6.0)
    i = np.floor(h).astype(int)
    f = h - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    r = np.choose(i, [v, q, p, p, t, v], mode="clip")
    g = np.choose(i, [t, v, v, q, p, p], mode="clip")
    b = np.choose(i, [p, p, t, v, v, q], mode="clip")
    gris = s <= 0
    return np.stack([np.where(gris, v, r), np.where(gris, v, g), np.where(gris, v, b)], axis=-1)


def _srgb_encode(x):
    """dng_function_GammaEncode_sRGB."""
    x = np.asarray(x, float)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(np.maximum(x, 0.0031308), 1 / 2.4) - 0.055)


def _srgb_decode(y):
    y = np.asarray(y, float)
    return np.where(y <= 0.0031308 * 12.92, y / 12.92, np.power((np.maximum(y, 0.0031308 * 12.92) + 0.055) / 1.055, 2.4))


def _table_1d(f):
    """dng_1d_table : 4097 échantillons de f sur [0,1], interpolation linéaire."""
    x = np.arange(4097) / 4096.0
    return f(x)


def _interp_1d(tab, x):
    return np.interp(np.clip(x, 0.0, 1.0), np.arange(4097) / 4096.0, tab)


def appliquer_table_hsv(rgb, table, encodage):
    """RefBaselineHueSatMap (dng_reference.cpp) : HueSatMap ou LookTable.

    table (V,H,S,3) = (décalage de teinte en degrés, échelle de saturation,
    échelle de valeur) ; V=1 : table « 2.5D », sans encodage de la valeur
    (comme le SDK, qui décode quand même la valeur en sortie si l'encodage est
    sRGB).  Teinte circulaire (indice H-1 -> 0), saturation bornée à 1,
    valeur bornée à [0,1].
    """
    V, H, S, _ = table.shape
    avec_enc = encodage == 1
    hsv = rgb_vers_hsv(rgb)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    h_scale = 0.0 if H < 2 else H * (1.0 / 6.0)
    hs = h * h_scale
    ss = s * (S - 1)
    h0 = np.floor(hs).astype(int)
    s0 = np.minimum(np.floor(ss).astype(int), S - 2)
    h1 = h0 + 1
    rebouclage = h0 >= H - 1
    h0 = np.where(rebouclage, H - 1, h0)
    h1 = np.where(rebouclage, 0, h1)
    hf1 = hs - h0
    sf1 = ss - s0
    hf0, sf0 = 1.0 - hf1, 1.0 - sf1
    if V < 2:
        v_enc = v
        v0 = np.zeros_like(h0)
        vf1 = np.zeros_like(hs)
    else:
        v_enc = _srgb_encode(np.clip(v, 0.0, 1.0)) if avec_enc else v
        vs = v_enc * (V - 1)
        v0 = np.minimum(np.floor(vs).astype(int), V - 2)
        vf1 = vs - v0
    vf0 = 1.0 - vf1

    def plan(vi):
        e00 = table[vi, h0, s0]
        e01 = table[vi, h1, s0]
        e10 = table[vi, h0, s0 + 1]
        e11 = table[vi, h1, s0 + 1]
        a = hf0[..., None] * e00 + hf1[..., None] * e01
        b = hf0[..., None] * e10 + hf1[..., None] * e11
        return sf0[..., None] * a + sf1[..., None] * b

    res = plan(v0)
    if V >= 2:
        res = vf0[..., None] * res + vf1[..., None] * plan(v0 + 1)
    dh, ds, dv = res[..., 0], res[..., 1], res[..., 2]
    h = h + dh * (6.0 / 360.0)
    s = np.minimum(s * ds, 1.0)
    v_enc = np.clip(v_enc * dv, 0.0, 1.0)
    v = _srgb_decode(v_enc) if avec_enc else v_enc
    return hsv_vers_rgb(np.stack([h, s, v], axis=-1))


def _carte_interpolee(p, spec, xy):
    """dng_camera_profile::HueSatMapForWhite : mélange des deux cartes en 1/T."""
    if p.hsm1 is None:
        return None
    if p.hsm2 is None or spec.t1 == spec.t2:
        return p.hsm1
    g = spec.poids(xy)
    if spec.inversion_hsm:
        g = 1.0 - g
    if g >= 1.0:
        return p.hsm1
    if g <= 0.0:
        return p.hsm2
    return g * p.hsm1 + (1.0 - g) * p.hsm2


# ------------------------------------------------------ courbes (étapes 3, 5)

class SplineAdobe:
    """dng_spline_solver (dng_spline.cpp) : spline C1 (pentes par système
    tridiagonal, dérivée seconde nulle aux extrémités), segments de Bézier."""

    def __init__(self, points):
        pts = np.asarray(points, float).reshape(-1, 2)
        self.X, self.Y = pts[:, 0].copy(), pts[:, 1].copy()
        X, Y = self.X, self.Y
        n = len(X)
        S = np.zeros(n)
        A = X[1] - X[0]
        B = (Y[1] - Y[0]) / A
        S[0] = B
        for j in range(2, n):
            C = X[j] - X[j - 1]
            D = (Y[j] - Y[j - 1]) / C
            S[j - 1] = (B * C + D * A) / (A + C)
            A, B = C, D
        S[n - 1] = 2.0 * B - S[n - 2]
        S[0] = 2.0 * S[0] - S[1]
        if n > 2:
            E, F, G = np.zeros(n), np.zeros(n), np.zeros(n)
            F[0] = 0.5
            E[n - 1] = 0.5
            G[0] = 0.75 * (S[0] + S[1])
            G[n - 1] = 0.75 * (S[n - 2] + S[n - 1])
            for j in range(1, n - 1):
                A = (X[j + 1] - X[j - 1]) * 2.0
                E[j] = (X[j + 1] - X[j]) / A
                F[j] = (X[j] - X[j - 1]) / A
                G[j] = 1.5 * S[j]
            for j in range(1, n):
                A = 1.0 - F[j - 1] * E[j]
                if j != n - 1:
                    F[j] /= A
                G[j] = (G[j] - G[j - 1] * E[j]) / A
            for j in range(n - 2, -1, -1):
                G[j] = G[j] - F[j] * G[j + 1]
            S = G
        self.S = S

    def __call__(self, x):
        x = np.asarray(x, float)
        X, Y, S = self.X, self.Y, self.S
        j = np.clip(np.searchsorted(X, x, side="left"), 1, len(X) - 1)
        x0, x1, y0, y1, s0, s1 = X[j - 1], X[j], Y[j - 1], Y[j], S[j - 1], S[j]
        A = x1 - x0
        B = (x - x0) / A
        C = (x1 - x) / A
        d = ((y0 * (2.0 - C + B) + s0 * A * B) * C * C) + ((y1 * (2.0 - B + C) - s1 * A * C) * B * B)
        d = np.where(x <= X[0], Y[0], np.where(x >= X[-1], Y[-1], d))
        return d


def courbe_acr3(x):
    """dng_tone_curve_acr3_default::Evaluate : table de 1025 valeurs, interpolation linéaire."""
    n = len(ACR3)
    y = np.asarray(x, float) * (n - 1)
    i = np.clip(np.floor(y).astype(int), 0, n - 2)
    f = y - i
    return ACR3[i] * (1.0 - f) + ACR3[i + 1] * f


def _rampe_exposition(x, white, black):
    """dng_function_exposure_ramp::Evaluate (noir=0 : simple échelle 1/white)."""
    slope = 1.0 / (white - black)
    rayon = min(0.5 * black, (1.0 / 16.0) / slope)
    qscale = slope / (4.0 * rayon) if rayon > 0 else 0.0
    bas = x <= black - rayon
    haut = x >= black + rayon
    return np.where(bas, 0.0, np.where(haut, np.minimum((x - black) * slope, 1.0),
                                       qscale * (x - (black - rayon)) ** 2))


def _exposition_negative(x, expo):
    """dng_function_exposure_tone : assombrit la courbe (expo < 0), NOP sinon."""
    if expo >= 0.0:
        return x
    pente = 2.0 ** expo
    a = 16.0 / 9.0 * (1.0 - pente)
    b = pente - 0.5 * a
    c = 1.0 - a - b
    return np.where(x <= 0.25, x * pente, (a * x + b) * x + c)


def _appliquer_tonalite(rgb, tab):
    """RefBaselineRGBTone (dng_reference.cpp) : la courbe est appliquée au canal max
    et au canal min, le canal intermédiaire est interpolé entre les deux (teinte
    conservée).  Les 7 cas du SDK reviennent tous à cette formule ; gris : courbe seule."""
    hi = np.max(rgb, axis=-1, keepdims=True)
    lo = np.min(rgb, axis=-1, keepdims=True)
    hi_t, lo_t = _interp_1d(tab, hi), _interp_1d(tab, lo)
    ecart = hi - lo
    ok = ecart > 0
    return np.where(ok, lo_t + (hi_t - lo_t) * (rgb - lo) / np.where(ok, ecart, 1.0), hi_t)


# ------------------------------------------------------------- rendu complet

def rendre(cam_rgb, wb_neutral, profil, exposition_il=0.0, *, exposition_base=0.0,
           ombres=0.0, courbe="profil", ab=None, cc=None,
           prophoto_vers_xyz=None):
    """Rendu Adobe d'échantillons caméra -> ProPhoto linéaire (N,3), valeurs dans [0,1].

    cam_rgb          : (N,3) RGB caméra linéaire, noir soustrait, saturation = 1.
    wb_neutral       : (3,) CameraNeutral (AsShotNeutral).
    profil           : Profil (charger_dcp) ou dict de dcp.lire().
    exposition_il    : réglage d'exposition en IL (dng_render::Exposure).
    exposition_base  : BaselineExposure du négatif (la valeur qu'Adobe applique
                       aux 3FR est inconnue ; 0 par défaut).  Le BaselineExposureOffset
                       du profil est ajouté tout seul (dng_negative::TotalBaselineExposure).
    ombres           : réglage « Shadows » du SDK (noir = ombres*0,001 ; 5 par défaut dans
                       le SDK, 0 ici : dcamprof n'en applique pas).  Ignoré si le profil
                       dit DefaultBlackRender = None.
    courbe           : "profil" (courbe du profil, sinon ACR3), "acr3", None (identité)
                       ou tableau de points (x,y) (spline Adobe).
    prophoto_vers_xyz: matrice ProPhoto->XYZ D50 (SDK 4 chiffres par défaut).
    """
    if isinstance(profil, dict):
        profil = charger_dcp_dict(profil)
    m_pp = PROPHOTO_VERS_XYZ_SDK if prophoto_vers_xyz is None else np.asarray(prophoto_vers_xyz, float)
    cam = np.atleast_2d(np.asarray(cam_rgb, float))
    spec = SpecCouleur(profil, ab, cc)
    xy = spec.neutre_vers_xy(np.asarray(wb_neutral, float))
    cam2pcs, blanc = spec.camera_vers_pcs(xy)

    # 1. caméra -> ProPhoto (RefBaselineABCtoRGB : écrêtage au blanc caméra puis [0,1])
    cam = np.minimum(cam, blanc)
    rgb = np.clip(cam @ (np.linalg.inv(m_pp) @ cam2pcs).T, 0.0, 1.0)

    # 2. HueSatMap
    carte = _carte_interpolee(profil, spec, xy)
    if carte is not None:
        rgb = appliquer_table_hsv(rgb, carte, profil.hsm_encodage)

    # 3. exposition (dng_render_task::Start)
    expo = exposition_il + exposition_base + profil.exposition_base_profil
    white = 1.0 / 2.0 ** max(0.0, expo)
    noir = 0.0 if profil.noir_defaut_aucun else ombres * 0.001
    noir = min(noir, 0.99 * white)
    rgb = _interp_1d(_table_1d(lambda x: _rampe_exposition(x, white, noir)), rgb)

    # 4. LookTable
    if profil.look is not None:
        rgb = appliquer_table_hsv(rgb, profil.look, profil.look_encodage)

    # 5. exposition négative o courbe de tonalité
    if isinstance(courbe, str) and courbe == "profil":
        courbe = "acr3" if profil.courbe is None else profil.courbe
    if courbe is None:
        f = lambda x: x
    elif isinstance(courbe, str) and courbe == "acr3":
        f = courbe_acr3
    else:
        f = SplineAdobe(courbe)
    tab = _table_1d(lambda x: f(np.clip(_exposition_negative(x, expo), 0.0, 1.0)))
    return _appliquer_tonalite(rgb, tab)


def rendre_xyz_d50(cam_rgb, wb_neutral, profil, exposition_il=0.0, **kw):
    """Idem, en XYZ D50 (ProPhoto linéaire -> XYZ)."""
    m_pp = PROPHOTO_VERS_XYZ_SDK if kw.get("prophoto_vers_xyz") is None else np.asarray(kw["prophoto_vers_xyz"], float)
    return rendre(cam_rgb, wb_neutral, profil, exposition_il, **kw) @ m_pp.T


def rendre_srgb(cam_rgb, wb_neutral, profil, exposition_il=0.0, *, en_8bits=True, **kw):
    """Idem, en sRGB codé (dng_space_sRGB, gamma sRGB) : entiers 0-255 (uint8) ou flottants [0,1]."""
    xyz = rendre_xyz_d50(cam_rgb, wb_neutral, profil, exposition_il, **kw)
    lin = np.clip(xyz @ np.linalg.inv(SRGB_VERS_XYZ_D50).T, 0.0, 1.0)
    enc = _srgb_encode(lin)
    return np.clip(np.floor(enc * 255.0 + 0.5), 0, 255).astype(np.uint8) if en_8bits else enc


# ================================================================== self-test

DCP_ADOBE = ("/Library/Application Support/Adobe/CameraRaw/CameraProfiles/Adobe Standard/"
             "Hasselblad 100-22-Coated6 Adobe Standard.dcp")
import os  # noqa: E402
DCAMPROF = os.environ.get('HNCS_DCAMPROF', 'dcamprof')
TMP = pathlib.Path(os.environ.get('HNCS_WORKDIR', 'workdir')).resolve() / 'tmp-chaine'
GAMMA_DCAMPROF = 461.0 / 256.0      # gamma des TIFF ProPhoto de dcamprof (render_test_tiff)


def neutre_pour_balance(profil, temp, tint=0.0):
    """CameraNeutral (max = 1) cohérent avec une balance (T, tint) : CM(xy)·XYZ(xy)."""
    spec = SpecCouleur(profil)
    xy = temp_vers_xy(temp, tint)
    n = spec.xyz_vers_camera(xy) @ xy_vers_xyz(xy)
    for _ in range(10):     # CM dépend de xy, déjà exact ; la boucle sert la température rebouclée
        xy2 = spec.neutre_vers_xy(n / n.max())
        n = spec.xyz_vers_camera(xy2) @ xy_vers_xyz(xy2)
    return n / n.max()


def _delta_e_2000(xyz1, xyz2):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import colour
        lab1 = colour.XYZ_to_Lab(xyz1, illuminant=np.array(D50_XY))
        lab2 = colour.XYZ_to_Lab(xyz2, illuminant=np.array(D50_XY))
        return np.asarray(colour.delta_E(lab1, lab2, method="CIE 2000"))


# --- lecture / réécriture minimale d'un DCP (test uniquement : variantes du profil Adobe)

def _dcp_brut(chemin):
    import struct
    d = pathlib.Path(chemin).read_bytes()
    off = struct.unpack_from("<I", d, 4)[0]
    n = struct.unpack_from("<H", d, off)[0]
    tailles = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
    out = {}
    for i in range(n):
        tag, typ, cnt, val = struct.unpack_from("<HHII", d, off + 2 + 12 * i)
        t = tailles[typ] * cnt
        pos = off + 2 + 12 * i + 8 if t <= 4 else val
        out[tag] = (typ, cnt, d[pos:pos + t])
    return out


def _ecrire_dcp(chemin, tags):
    import struct
    corps = bytearray()
    entrees = []
    for tag in sorted(tags):
        typ, cnt, brut = tags[tag]
        if len(brut) <= 4:
            entrees.append(struct.pack("<HHI", tag, typ, cnt) + brut.ljust(4, b"\0"))
        else:
            while (8 + len(corps)) % 4:
                corps += b"\0"
            entrees.append(struct.pack("<HHII", tag, typ, cnt, 8 + len(corps)))
            corps += brut
    while (8 + len(corps)) % 4:
        corps += b"\0"
    ifd = 8 + len(corps)
    data = b"IIRC" + struct.pack("<I", ifd) + bytes(corps) + struct.pack("<H", len(entrees)) \
        + b"".join(entrees) + struct.pack("<I", 0)
    pathlib.Path(chemin).write_bytes(data)


def _variante_dcp(src, dst, courbe_xy=None, retirer_courbe=False, look_srgb=False):
    import struct
    t = _dcp_brut(src)
    if retirer_courbe:
        t.pop(50940, None)
    if courbe_xy is not None:
        a = np.asarray(courbe_xy, "<f4").reshape(-1)
        t[50940] = (11, a.size, a.tobytes())
    if look_srgb:
        t[51108] = (4, 1, struct.pack("<I", 1))
    _ecrire_dcp(dst, t)


# --- tests

class _Bilan:
    def __init__(self):
        self.echecs = []

    def ok(self, nom, cond, detail=""):
        print("  [%s] %s %s" % ("OK" if cond else "ECHEC", nom, detail))
        if not cond:
            self.echecs.append(nom)


def _profil_test():
    return charger_dcp(DCP_ADOBE)


def _balances(p):
    return [(t, ti, neutre_pour_balance(p, t, ti)) for t, ti in
            [(2850, 0), (3600, 0), (4500, 10), (5200, 0), (5200, 25), (6500, 0), (9500, 0)]]


def test_a_neutres(b):
    print("(a) gris neutre -> neutre")
    p = _profil_test()
    pire = 0.0
    for t, ti, n in _balances(p):
        k = np.linspace(0.005, 1.0, 80)[:, None]
        for kw in ({}, {"prophoto_vers_xyz": PROPHOTO_VERS_XYZ_ICC}):
            rgb = rendre(k * n[None, :], n, p, **kw)
            pire = max(pire, float(np.max(np.ptp(rgb, axis=1))))
    b.ok("écart max entre canaux d'un gris (toutes balances)", pire < 1e-3, "= %.1e" % pire)
    # sans ForwardMatrix (procédure CM + Bradford de la spec)
    p2 = dataclasses.replace(p, fm1=None, fm2=None)
    pire = 0.0
    for t, ti, n in _balances(p2):
        k = np.linspace(0.005, 1.0, 40)[:, None]
        pire = max(pire, float(np.max(np.ptp(rendre(k * n[None, :], n, p2), axis=1))))
    b.ok("idem sans ForwardMatrix (Bradford)", pire < 1e-3, "= %.1e" % pire)
    # une seule paire matrice/illuminant
    p3 = dataclasses.replace(p, cm2=None, fm2=None, hsm2=None, ill2=0)
    n = neutre_pour_balance(p3, 5200)
    r = rendre(np.linspace(0.01, 1, 20)[:, None] * n, n, p3)
    b.ok("idem illuminant unique", float(np.max(np.ptp(r, axis=1))) < 1e-3)


def test_b_identite(b):
    print("(b) HueSatMap / LookTable identité = aucun effet")
    p = _profil_test()
    nu = dataclasses.replace(p, hsm1=None, hsm2=None, look=None)
    rng = np.random.default_rng(1)
    cam = rng.random((4000, 3))
    n = neutre_pour_balance(p, 5200)
    cam = cam * n
    ref = rendre(cam, n, nu)
    for (H, S, V, enc) in [(12, 5, 1, 0), (36, 8, 16, 0), (36, 8, 16, 1), (6, 4, 3, 1), (1, 3, 1, 0)]:
        tab = np.zeros((V, H, S, 3))
        tab[..., 1] = 1.0
        tab[..., 2] = 1.0
        q = dataclasses.replace(nu, hsm1=tab, hsm2=tab, hsm_encodage=enc, look=tab, look_encodage=enc)
        d = float(np.max(np.abs(rendre(cam, n, q) - ref)))
        b.ok("table identité %dx%dx%d enc=%d" % (H, S, V, enc), d < 1e-9, "(écart %.1e)" % d)
    # conventions : décalage +30 deg, saturation x0,5, valeur x0,8 (table constante)
    tab = np.zeros((1, 4, 3, 3))
    tab[..., 0], tab[..., 1], tab[..., 2] = 30.0, 0.5, 0.8
    rgb = np.array([[0.8, 0.3, 0.2], [0.2, 0.5, 0.9], [0.1, 0.9, 0.4]])
    h0 = rgb_vers_hsv(rgb)
    h1 = rgb_vers_hsv(appliquer_table_hsv(rgb, tab, 0))
    b.ok("décalage de teinte +30 deg (teinte circulaire)", np.allclose(np.mod(h1[:, 0] - h0[:, 0], 6.0), 0.5))
    b.ok("échelle de saturation x0,5", np.allclose(h1[:, 1], 0.5 * h0[:, 1]))
    b.ok("échelle de valeur x0,8", np.allclose(h1[:, 2], 0.8 * h0[:, 2]))
    g = np.array([[0.4, 0.4, 0.4]])
    b.ok("saturation 0 = neutre conservé", np.allclose(appliquer_table_hsv(g, tab, 0)[0, 0] - appliquer_table_hsv(g, tab, 0)[0, 2], 0))
    # aller-retour HSV
    c = rng.random((1000, 3))
    b.ok("RGB->HSV->RGB", np.allclose(hsv_vers_rgb(rgb_vers_hsv(c)), c, atol=1e-12))


def test_c_courbes(b):
    print("(c) courbes : monotonie, passage par les points")
    x = np.linspace(0, 1, 20001)
    y = courbe_acr3(x)
    b.ok("ACR3 monotone croissante, 0->0, 1->1", np.all(np.diff(y) >= 0) and y[0] == 0 and y[-1] == 1)
    pts = [(0, 0), (0.1, 0.06), (0.3, 0.27), (0.55, 0.6), (0.8, 0.88), (1, 1)]
    sp = SplineAdobe(pts)
    ys = sp(x)
    b.ok("spline Adobe passe par ses points", np.allclose(sp(np.array([p[0] for p in pts])), [p[1] for p in pts]))
    b.ok("spline Adobe monotone (points croissants)", np.all(np.diff(ys) >= -1e-12))
    h = 1e-6
    dd = (sp(np.array([0.3 + h])) - sp(np.array([0.3 - h]))) / (2 * h)
    d1 = (sp(np.array([0.3 + 2 * h])) - sp(np.array([0.3 + h]))) / h
    d0 = (sp(np.array([0.3 - h])) - sp(np.array([0.3 - 2 * h]))) / h
    b.ok("spline C1 aux nœuds", abs(d1 - d0) < 1e-3)
    p = _profil_test()
    n = neutre_pour_balance(p, 5200)
    k = np.linspace(0, 1, 500)[:, None]
    for nom, kw in [("courbe ACR3", {}), ("spline du profil", {"courbe": pts}),
                    ("exposition +1", {"exposition_il": 1.0}), ("exposition -1,5", {"exposition_il": -1.5})]:
        r = rendre(k * n, n, p, **kw)
        b.ok("rampe de gris monotone (%s)" % nom, bool(np.all(np.diff(r[:, 1]) >= -1e-9)))
    # exposition : aucune table, courbe identité
    nu = dataclasses.replace(p, hsm1=None, hsm2=None, look=None)
    g = 0.1 * n[None, :]
    r0 = rendre(g, n, nu, courbe=None)[0, 1]
    r1 = rendre(g, n, nu, courbe=None, exposition_il=1.0)[0, 1]
    b.ok("exposition +1 IL = x2 avant la courbe", abs(r1 / r0 - 2.0) < 1e-3, "(%.4f)" % (r1 / r0))
    r2 = rendre(g, n, nu, courbe=None, exposition_il=-1.0)[0, 1]
    b.ok("exposition -1 IL = /2 (zone basse de la courbe d'exposition)", abs(r2 / r0 - 0.5) < 1e-3, "(%.4f)" % (r2 / r0))
    blanc = rendre(n[None, :], n, nu, courbe=None, exposition_il=-1.0)[0, 1]
    b.ok("exposition -1 IL : le blanc reste blanc", abs(blanc - 1.0) < 2e-3, "(%.4f)" % blanc)
    off = dataclasses.replace(nu, exposition_base_profil=1.0)
    r3 = rendre(g, n, off, courbe=None)[0, 1]
    b.ok("BaselineExposureOffset du profil appliqué", abs(r3 / r0 - 2.0) < 1e-3)
    s = rendre_srgb(n[None, :] * 0.18, n, nu, courbe=None)
    b.ok("sortie sRGB 8 bits neutre", s.dtype == np.uint8 and np.ptp(s[0].astype(int)) <= 1, str(s[0]))
    for t in (2000, 2850, 4000, 6500, 12000):
        xy = temp_vers_xy(t, 15)
        t2, ti2 = xy_vers_temp(xy)
        if abs(t2 - t) > 0.5 or abs(ti2 - 15) > 0.2:
            b.ok("température <-> xy", False, "%d -> %.1f, tint %.2f" % (t, t2, ti2))
            return
    b.ok("température <-> xy (aller-retour)", True)


def _tiff16(chemin, rgb_u16):
    import cv2
    h, w = 80, rgb_u16.shape[0] // 80
    img = rgb_u16[:h * w].reshape(h, w, 3)[..., ::-1]     # cv2 écrit en BGR
    assert cv2.imwrite(str(chemin), np.ascontiguousarray(img))


def _lire_tiff16(chemin):
    import cv2
    img = cv2.imread(str(chemin), cv2.IMREAD_UNCHANGED)
    return img[..., ::-1].reshape(-1, 3)


def test_d_dcamprof(b):
    import subprocess
    import time
    print("(d) comparaison avec dcamprof 1.0.6 (test-profile sur image de test)")
    import shutil
    if not (shutil.which(DCAMPROF) or pathlib.Path(DCAMPROF).exists()) or not pathlib.Path(DCP_ADOBE).exists():
        # dcamprof is optional (see README): without it, or without Adobe's profile, this cross-check is skipped, not failed
        print("  IGNORE : dcamprof (HNCS_DCAMPROF) ou le profil Adobe introuvable, contrôle facultatif")
        return
    try:
        import cv2     # noqa: F401
    except ImportError:
        print("  IGNORE : cv2 absent, contrôle facultatif")
        return
    rep = TMP / "dcamprof-test"
    rep.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    n_px = 4000
    p_lin = rng.random((n_px, 3))
    p_lin[:300] = np.linspace(0.0, 1.0, 300)[:, None]                     # rampe de gris
    p_lin[300:420] = rng.choice([0.0, 1.0], size=(120, 3)) * rng.random((120, 1)) * 0.9 + 0.02   # forte saturation
    u16 = np.round(p_lin ** (1 / GAMMA_DCAMPROF) * 65535).astype(np.uint16)
    p_q = (u16 / 65535.0) ** GAMMA_DCAMPROF     # ce que dcamprof relit
    _tiff16(rep / "entree.tif", u16)

    p0 = _profil_test()
    courbe_xy = SplineAdobe([(0, 0), (0.1, 0.07), (0.3, 0.3), (0.6, 0.66), (0.85, 0.92), (1, 1)])
    xs = np.linspace(0, 1, 1025)
    pts_c = np.stack([xs, courbe_xy(xs)], axis=1)       # échantillonnage régulier (dcamprof ignore les x)
    _variante_dcp(DCP_ADOBE, rep / "acr3.dcp")                                   # sans courbe -> ACR3
    _variante_dcp(DCP_ADOBE, rep / "courbe.dcp", courbe_xy=pts_c)
    _variante_dcp(DCP_ADOBE, rep / "look_srgb.dcp", look_srgb=True)
    variantes = [
        ("matrice seule (-L)", "acr3.dcp", ["-L"], dict(hsm=False, look=False)),
        ("+ HueSatMap (-P)", "acr3.dcp", ["-P"], dict(hsm=True, look=False)),
        ("complet, courbe ACR3", "acr3.dcp", [], dict(hsm=True, look=True)),
        ("complet, courbe du profil", "courbe.dcp", [], dict(hsm=True, look=True)),
        ("complet, LookTable sRGB 3D", "look_srgb.dcp", [], dict(hsm=True, look=True)),
    ]
    balances = [(2850, 0), (4300, 8), (5200, 0), (6500, -10), (9000, 0)]
    pire_global = 0.0
    resume = []
    for nom, fic, flags, opt in variantes:
        prof = charger_dcp(rep / fic)
        if not opt["hsm"]:
            prof = dataclasses.replace(prof, hsm1=None, hsm2=None, look=None)
        elif not opt["look"]:
            prof = dataclasses.replace(prof, look=None)
        if fic == "acr3.dcp":
            assert prof.courbe is None
        stats = []
        for t, ti in balances:
            n = neutre_pour_balance(p0, t, ti)
            cam = p_q * n
            t0 = time.time()
            cmd = [DCAMPROF, "test-profile"] + flags + ["-w", "%.10f,%.10f,%.10f" % tuple(n),
                                                          str(rep / "entree.tif"), str(rep / fic), str(rep / "sortie.tif")]
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(rep), timeout=600)
            if r.returncode != 0 or not (rep / "sortie.tif").exists():
                b.ok("dcamprof %s %d K" % (nom, t), False, (r.stderr or r.stdout)[-300:])
                continue
            ref = (_lire_tiff16(rep / "sortie.tif") / 65535.0) ** GAMMA_DCAMPROF
            (rep / "sortie.tif").unlink()
            moi = rendre(cam, n, prof, prophoto_vers_xyz=PROPHOTO_VERS_XYZ_ICC)
            de = _delta_e_2000(moi @ PROPHOTO_VERS_XYZ_ICC.T, ref @ PROPHOTO_VERS_XYZ_ICC.T)
            moi_sdk = rendre(cam, n, prof)
            de_sdk = _delta_e_2000(moi_sdk @ PROPHOTO_VERS_XYZ_SDK.T, ref @ PROPHOTO_VERS_XYZ_ICC.T)
            stats.append((t, float(de.mean()), float(np.percentile(de, 99)), float(de.max()), float(de_sdk.max()), time.time() - t0))
        for (t, mo, p99, mx, mx_sdk, dt) in stats:
            print("      %-28s %5d K : dE2000 moyen %.4f, p99 %.4f, max %.4f | matrice SDK 4 chiffres : max %.4f"
                  % (nom, t, mo, p99, mx, mx_sdk))
        pire = max([s[3] for s in stats] + [0.0])
        pire_global = max(pire_global, pire)
        resume.append((nom, pire, max([s[4] for s in stats] + [0.0])))
        b.ok("dcamprof : %s (%d balances)" % (nom, len(stats)), len(stats) == len(balances) and pire < 0.5,
             "pire dE2000 = %.4f" % pire)
    print("  résumé (pire ΔE2000 sur échantillons, matrice ICC identique des deux côtés / matrice SDK) :")
    for nom, a, c in resume:
        print("      %-28s %.4f / %.4f" % (nom, a, c))
    print("  pire écart global : %.4f" % pire_global)
    for f in rep.glob("*"):
        f.unlink()
    rep.rmdir()


def self_test():
    b = _Bilan()
    test_a_neutres(b)
    test_b_identite(b)
    test_c_courbes(b)
    test_d_dcamprof(b)
    print()
    if b.echecs:
        print("ECHEC : " + ", ".join(b.echecs))
        return 1
    print("TOUT PASSE")
    return 0


def _cli(argv):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--dcp")
    ap.add_argument("--cam", help="r,g,b caméra linéaire")
    ap.add_argument("--wb", help="CameraNeutral r,g,b")
    ap.add_argument("--exposition", type=float, default=0.0)
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.dcp and a.cam and a.wb:
        p = charger_dcp(a.dcp)
        cam = [float(x) for x in a.cam.split(",")]
        wb = [float(x) for x in a.wb.split(",")]
        print("ProPhoto lin :", rendre(cam, wb, p, a.exposition)[0])
        print("sRGB 8 bits  :", rendre_srgb(cam, wb, p, a.exposition)[0])
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))

