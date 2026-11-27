--[[
  regle.lua : la règle des réglages par photo du X2D II, SANS aucune API Lightroom (testable avec un Lua ordinaire).

  Version 1.1.0 : les coefficients des photos avec décisions du boîtier et du haut ISO ont été mesurés dans Camera Raw
  contre des exports Phocus, avec le profil HNCS 2.0, puis figés avant la validation sur des photos tenues à part (voir
  le README du dépôt). 1.1 ajoute une correction d'Exposition par objectif, seulement pour « sans décisions du boîtier,
  ISO < 6400 » (les autres classes ne cumulent pas). Objectif inconnu = 0. Les valeurs sont celles du README ; n'en
  changer aucune sans changer le README.
  Version 1.2.0 : photos avec décisions du boîtier : classe 0 à -0,05 d'Exposition et, corrections d'objectif actives, un ajout
  d'Exposition par objectif (AJOUT_ACTIVES_DECISIONS) ; RAW seul, corrections coupées, 55V : -0,08.

  Compatible Lua 5.1 (celui de Lightroom Classic) : pas de `//`, pas de `goto`, pas d'opérateurs de bits.
]]

local M = {}

M.PROFIL = "HNCS"                      -- nom du profil (2.0) dans Lightroom / Camera Raw
-- Règle 1.2 (gardée) : ISO_HAUT = 3200 (même valeur d'exposition) ; seul le seuil change avec la 2.0
M.ISO_HAUT = 6400                      -- RAW seul, ISO >= 6400 (profil 2.0)
M.EXPO_ISO_HAUT = -0.15

-- 1.1 : correction d'Exposition par objectif (curseur Exposition, profil 2.0).
-- ACTIVES : corrections d'objectif de Lightroom / Camera Raw actives (profil d'objectif Adobe, vignettage compris) ;
-- COUPEES : corrections coupées. Choisi d'après le réglage de la photo (LensProfileEnable) ; inconnu = coupées.
M.EXPO_OBJECTIF_ACTIVES = { ["55V"] = -0.15, ["38V"] = -0.20, ["35-100E"] = -0.05, ["120"] = -0.10, ["135"] = -0.09,
  ["20-35E"] = -0.08, ["25V"] = -0.05, ["90V"] = 0.0 }
M.EXPO_OBJECTIF_COUPEES = { ["55V"] = -0.08, ["38V"] = -0.05, ["35-100E"] = -0.03, ["120"] = -0.10, ["135"] = -0.09,
  ["20-35E"] = -0.08, ["25V"] = -0.05, ["90V"] = 0.0 }
M.OBJECTIFS = { ["55V"] = true, ["38V"] = true, ["35-100E"] = true, ["120"] = true, ["135"] = true,
  ["20-35E"] = true, ["25V"] = true, ["90V"] = true }

-- Nom d'objectif (EXIF LensModel ou nom donné par Lightroom) -> clé de table, ou nil. Il faut le mot XCD (jamais un HC)
-- et un mot connu : « XCD 55V », « XCD 2,8-4/35-100E »... Mots = suites de lettres, chiffres et tirets, en majuscules.
function M.objectif_court(nom)
  if type(nom) ~= "string" then return nil end
  local mots, xcd = {}, false
  for m in nom:upper():gmatch("[%w%-]+") do
    if m == "XCD" then xcd = true end
    mots[#mots + 1] = m
  end
  if not xcd then return nil end
  for _, m in ipairs(mots) do
    if M.OBJECTIFS[m] then return m end
  end
  return nil
end

-- -> clé d'objectif, valeur du curseur Exposition ; (nil, 0.0) pour un objectif inconnu.
function M.expo_objectif(nom, actives)
  local k = M.objectif_court(nom)
  if k == nil then return nil, 0.0 end
  if actives == true then return k, M.EXPO_OBJECTIF_ACTIVES[k] end
  return k, M.EXPO_OBJECTIF_COUPEES[k]
end

-- BaselineExposure arrondie (0, 1, 2) -> { exposition en IL, ombres, hautes lumières }
M.REGLE_TAGUEE = {
  [0] = { -0.05, 10, -5 },
  [1] = { -0.20, 5, -20 },
  [2] = { -0.10, 0, -50 },
}

-- 1.2 : photos avec décisions du boîtier, corrections d'objectif ACTIVES : ajout à l'Exposition de la classe, par objectif.
-- Absent = 0 (objectif inconnu, ou corrections coupées : pas d'ajout).
M.AJOUT_ACTIVES_DECISIONS = { ["55V"] = -0.15, ["35-100E"] = -0.04, ["38V"] = -0.13 }

-- Arrondi « au pair le plus proche » comme un arrondi bancaire (0.5 -> 0, 1.5 -> 2, 2.5 -> 2).
local function arrondi_pair(x)
  local f = math.floor(x)
  local d = x - f
  if d < 0.5 then
    return f
  elseif d > 0.5 then
    return f + 1
  elseif f % 2 == 0 then
    return f
  else
    return f + 1
  end
end
M.arrondi_pair = arrondi_pair

-- Troncature vers zéro.
local function tronque(x)
  if x >= 0 then return math.floor(x) end
  return math.ceil(x)
end

--[[
  Normalise un tableau de tags bruts { iso, be, sd, hl, kn } (nil = absent).
  sd / hl absents ou <= 0 -> nil (RAW seul : le boîtier écrit 0) ;
  256 = gain 1, présent et neutre. be absent -> 0.0. iso absent -> nil.
]]
function M.normaliser(t)
  local r = { fichier = t.fichier }
  for _, k in ipairs({ "sd", "hl" }) do
    local v = t[k]
    if type(v) == "number" and v > 0 then r[k] = tronque(v) else r[k] = nil end
  end
  local kn = t.kn
  if type(kn) == "number" then r.kn = tronque(kn) else r.kn = nil end
  if r.sd == nil or r.hl == nil then r.kn = nil end
  if type(t.iso) == "number" then r.iso = tronque(t.iso) else r.iso = nil end
  if type(t.lens) == "string" and t.lens ~= "" and t.lens ~= "-" then r.lens = t.lens else r.lens = nil end
  -- LensProfileEnable de Lightroom : 1 (ou true) = corrections actives ; 0 ou inconnu = coupées (l'erreur est asymétrique :
  -- appliquer la table « actives » à une photo aux corrections coupées assombrit de 0,1 IL environ, l'inverse sous-corrige seulement)
  r.lens_actives = (t.lens_actives == 1 or t.lens_actives == true)
  if type(t.be) == "number" then r.be = t.be * 1.0 else r.be = 0.0 end
  return r
end

--[[
  La règle. t = tags normalisés. Retourne exposition (IL), ombres, hautes lumières, motif, et une clé de cas (« raw_bas_iso », « raw_iso_haut »,
  « raw_bas_iso_objectif », « classe0 », « classe1 », « classe2 ») pour le résumé du module.
  expo_seule (variante) : ombres et hautes lumières à 0.
]]
function M.regle(t, expo_seule)
  if t.sd == nil or t.hl == nil then
    if t.iso ~= nil and t.iso >= M.ISO_HAUT then
      return M.EXPO_ISO_HAUT, 0, 0,
        string.format("sans tags, ISO %d >= %d", t.iso, M.ISO_HAUT), "raw_iso_haut"
    end
    local k, v = M.expo_objectif(t.lens, t.lens_actives)
    if k ~= nil and v ~= 0 then
      return v, 0, 0, string.format("sans tags (RAW seul), ISO < %d, objectif %s, corrections d'objectif %s : %+.2f",
        M.ISO_HAUT, k, t.lens_actives and "actives" or "coupées", v), "raw_bas_iso_objectif"
    end
    return 0.0, 0, 0, "sans tags (RAW seul) : rien à corriger", "raw_bas_iso"
  end
  local be = arrondi_pair(t.be)
  if be < 0 then be = 0 end
  if be > 2 then be = 2 end
  local c = M.REGLE_TAGUEE[be]
  local e, s, h = c[1], c[2], c[3]
  local motif = string.format("tags présents, BaselineExposure %+.2f -> classe %d", t.be, be)
  if t.lens_actives == true then
    local k = M.objectif_court(t.lens)
    local a = k and M.AJOUT_ACTIVES_DECISIONS[k]
    if a then
      e = e + a
      motif = motif .. string.format(", objectif %s, corrections d'objectif actives : %+.2f", k, a)
    end
  end
  if expo_seule then s, h = 0, 0 end
  return e, s, h, motif, "classe" .. string.format("%d", be)
end

return M
