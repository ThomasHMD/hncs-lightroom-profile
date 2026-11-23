--[[
  config.lua : tout ce qui dépend de Lightroom et se règle : chemin d'exiftool, et la CLÉ DU PROFIL.

  ===== CLÉ DU PROFIL CAMÉRA : UN SEUL ENDROIT =====
  D'après la documentation du SDK (LrPhoto:getDevelopSettings), le profil caméra est la clé « CameraProfile » (chaîne :
  le nom du profil tel que l'affiche Lightroom, ici « HNCS »). Vérifié dans Lightroom Classic :
  applyDevelopSettings accepte cette clé telle quelle et Lightroom retrouve le profil par son seul nom (sans
  CameraProfileDigest). Si un jour le profil ne change plus, c'est ICI qu'il faut corriger, nulle part ailleurs.
]]
local LrPrefs = import "LrPrefs"
local LrFileUtils = import "LrFileUtils"

local regle = require("regle")
local tags = require("tags")

local M = {}

M.CLE_PROFIL = "CameraProfile"
M.NOM_PROFIL = regle.PROFIL

-- Table à passer à photo:applyDevelopSettings : profil + trois curseurs, rien d'autre (les autres réglages de la photo
-- ne sont pas touchés). `profil_seul` (cas « rien à corriger ») : le profil seulement, les curseurs de la photo restent
-- tels quels (on n'efface pas un réglage fait à la main pour le remplacer par 0).
function M.reglages_developpement(exposition, ombres, hautes, profil_seul)
  local r = {}
  if not profil_seul then
    r.Exposure2012 = exposition
    r.Shadows2012 = ombres
    r.Highlights2012 = hautes
  end
  r[M.CLE_PROFIL] = M.NOM_PROFIL
  return r
end

M.NOM_HISTORIQUE = "Réglages X2D II (HNCS)"

local CANDIDATS = { "/opt/homebrew/bin/exiftool", "/usr/local/bin/exiftool", "/usr/bin/exiftool" }

local function prefs()
  return LrPrefs.prefsForPlugin()
end

function M.exiftool()
  local p = prefs().exiftool
  if p and p ~= "" then return p end
  for _, c in ipairs(CANDIDATS) do
    if LrFileUtils.exists(c) == "file" then return c end
  end
  return tags.EXIFTOOL_DEFAUT
end

function M.definir_exiftool(chemin)
  prefs().exiftool = chemin
end

return M
