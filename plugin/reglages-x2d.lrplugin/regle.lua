--[[
  regle.lua : la règle des réglages par photo du X2D II, SANS aucune API Lightroom (testable avec un Lua ordinaire).

  Les coefficients ont été mesurés dans Camera Raw contre des exports Phocus, avec le profil HNCS 2.0, puis figés
  avant la validation sur des photos tenues à part (voir le README du dépôt). Les valeurs du tableau ci-dessous sont
  exactement celles du README ; n'en changer aucune sans changer le README.

  Compatible Lua 5.1 (celui de Lightroom Classic) : pas de `//`, pas de `goto`, pas d'opérateurs de bits.
]]

local M = {}

M.PROFIL = "HNCS"                      -- nom du profil HNCS dans Lightroom / Camera Raw
-- Règle 1.2 (gardée) : ISO_HAUT = 3200 (même valeur d'exposition) ; seul le seuil change avec la 2.0
M.ISO_HAUT = 6400                      -- RAW seul, ISO >= 6400 (profil 2.0)
M.EXPO_ISO_HAUT = -0.15

-- BaselineExposure arrondie (0, 1, 2) -> { exposition en IL, ombres, hautes lumières }
M.REGLE_TAGUEE = {
  [0] = { 0.05, 10, -5 },
  [1] = { -0.20, 5, -20 },
  [2] = { -0.10, 0, -50 },
}

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
  if type(t.be) == "number" then r.be = t.be * 1.0 else r.be = 0.0 end
  return r
end

--[[
  La règle. t = tags normalisés. Retourne exposition (IL), ombres, hautes lumières, motif, et une clé de cas (« raw_bas_iso », « raw_iso_haut »,
  « classe0 », « classe1 », « classe2 ») pour le résumé du module.
  expo_seule (variante) : ombres et hautes lumières à 0.
]]
function M.regle(t, expo_seule)
  if t.sd == nil or t.hl == nil then
    if t.iso ~= nil and t.iso >= M.ISO_HAUT then
      return M.EXPO_ISO_HAUT, 0, 0,
        string.format("sans tags, ISO %d >= %d", t.iso, M.ISO_HAUT), "raw_iso_haut"
    end
    return 0.0, 0, 0, "sans tags (RAW seul) : rien à corriger", "raw_bas_iso"
  end
  local be = arrondi_pair(t.be)
  if be < 0 then be = 0 end
  if be > 2 then be = 2 end
  local c = M.REGLE_TAGUEE[be]
  local e, s, h = c[1], c[2], c[3]
  if expo_seule then s, h = 0, 0 end
  return e, s, h,
    string.format("tags présents, BaselineExposure %+.2f -> classe %d", t.be, be), "classe" .. string.format("%d", be)
end

return M
