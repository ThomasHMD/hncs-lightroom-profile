--[[
  Menu « Appliquer profil et réglages X2D II » : sur les photos SÉLECTIONNÉES, 3FR du Hasselblad X2D II seulement,
  lit BaselineExposure / ISO / décisions du boîtier (un seul exiftool, lecture seule), calcule Exposition / Ombres /
  Hautes lumières (règle dans regle.lua), applique le profil « HNCS » et ces trois curseurs en
  UNE opération annulable (Édition > Annuler), puis affiche un résumé.
]]
local LrApplication = import "LrApplication"
local LrDialogs = import "LrDialogs"
local LrTasks = import "LrTasks"
local LrPathUtils = import "LrPathUtils"
local LrFileUtils = import "LrFileUtils"

local regle = require("regle")
local tags = require("tags")
local config = require("config")

local LIBELLES = {
  raw_bas_iso = "RAW seul, ISO < 6400 : profil seulement, curseurs inchangés",
  raw_iso_haut = "RAW seul, ISO >= 6400 : exposition -0,15",
  classe0 = "RAW + JPEG, BaselineExposure ~ 0 : +0,05 / +10 / -5",
  classe1 = "RAW + JPEG, BaselineExposure ~ 1 : -0,20 / +5 / -20",
  classe2 = "RAW + JPEG, BaselineExposure ~ 2 : -0,10 / 0 / -50",
}
local ORDRE = { "raw_bas_iso", "raw_iso_haut", "classe0", "classe1", "classe2" }

-- Opérations système pour tags.lua (les chemins temporaires viennent de Lightroom).
local compteur = 0
local sys = {
  ecrire = function(chemin, texte)
    local f = assert(io.open(chemin, "wb"))
    f:write(texte)
    f:close()
  end,
  lire = function(chemin)
    local f = io.open(chemin, "rb")
    if not f then return nil end
    local texte = f:read("*a")
    f:close()
    return texte
  end,
  executer = function(commande) return LrTasks.execute(commande) end,
  fichier_temporaire = function(suffixe)
    compteur = compteur + 1
    return LrPathUtils.child(LrPathUtils.getStandardFilePath("temp"),
      "reglages-x2d-" .. tostring(os.time()) .. "-" .. tostring(compteur) .. suffixe)
  end,
  supprimer = function(chemin) if LrFileUtils.exists(chemin) == "file" then LrFileUtils.delete(chemin) end end,
}

LrTasks.startAsyncTask(function()
  -- Windows : non testé (chemins en barres obliques inversées et guillemets de la ligne de commande d'exiftool
  -- différents) ; on s'arrête plutôt que de risquer des résultats faux.
  if WIN_ENV then
    LrDialogs.message("Réglages X2D II",
      "Ce module n'a été essayé que sous macOS pour l'instant. Rien n'a été modifié.", "info")
    return
  end

  local catalog = LrApplication.activeCatalog()

  -- getTargetPhotos() renverrait TOUT le ruban si rien n'est sélectionné : on exige donc une sélection.
  if catalog:getTargetPhoto() == nil then
    LrDialogs.message("Réglages X2D II", "Aucune photo sélectionnée. Rien n'a été modifié.", "info")
    return
  end
  local photos = catalog:getTargetPhotos()

  local n_hors_format, n_hors_boitier, erreurs = 0, 0, {}
  local candidates, chemins, deja = {}, {}, {}
  for _, p in ipairs(photos) do
    local chemin = p:getRawMetadata("path")
    local ext = chemin and LrPathUtils.extension(chemin):lower() or ""
    if ext ~= "3fr" then
      n_hors_format = n_hors_format + 1
    else
      candidates[#candidates + 1] = { photo = p, chemin = chemin }
      if not deja[chemin] then
        deja[chemin] = true
        chemins[#chemins + 1] = chemin
      end
    end
  end

  if #candidates == 0 then
    LrDialogs.message("Réglages X2D II",
      "Aucun 3FR dans la sélection (" .. n_hors_format .. " photo(s) ignorée(s)). Rien n'a été modifié.", "info")
    return
  end

  local exiftool = config.exiftool()
  if LrFileUtils.exists(exiftool) ~= "file" then
    LrDialogs.message("Réglages X2D II",
      "exiftool est introuvable : " .. exiftool .. "\nIndique son chemin dans Bibliothèque > Modules externes > "
      .. "Réglages du module. Rien n'a été modifié.", "critical")
    return
  end

  local lus, message = tags.lire(chemins, exiftool, sys)
  if not lus then
    LrDialogs.message("Réglages X2D II", message .. "\nRien n'a été modifié.", "critical")
    return
  end

  -- Plan : calcul complet avant la moindre écriture.
  local plan, par_cas = {}, {}
  for _, c in ipairs(candidates) do
    local brut = lus[c.chemin]
    if brut == nil then
      erreurs[#erreurs + 1] = LrPathUtils.leafName(c.chemin) .. " : tags illisibles"
    elseif not tags.est_x2d2(brut) then
      n_hors_boitier = n_hors_boitier + 1
    else
      local t = regle.normaliser(brut)
      local e, s, h, _, cas = regle.regle(t, false)
      plan[#plan + 1] = { photo = c.photo, chemin = c.chemin, cas = cas,
        reglages = config.reglages_developpement(e, s, h, cas == "raw_bas_iso") }
    end
  end

  local n_modifiees = 0
  if #plan > 0 then
    local etat = catalog:withWriteAccessDo(config.NOM_HISTORIQUE, function()
      for _, a in ipairs(plan) do
        -- LrTasks.pcall et non pcall : applyDevelopSettings cède la main (yield), ce que pcall de Lua interdit
        -- (« Yielding is not allowed within a C or metamethod call », vu au premier essai dans Lightroom).
        local ok, err = LrTasks.pcall(function()
          a.photo:applyDevelopSettings(a.reglages, config.NOM_HISTORIQUE)
        end)
        if ok then
          n_modifiees = n_modifiees + 1
          par_cas[a.cas] = (par_cas[a.cas] or 0) + 1
        else
          erreurs[#erreurs + 1] = LrPathUtils.leafName(a.chemin) .. " : " .. tostring(err)
        end
      end
    end, { timeout = 60 })
    if etat == "aborted" then
      LrDialogs.message("Réglages X2D II",
        "Lightroom n'a pas donné l'accès au catalogue (occupé). Rien n'a été modifié ; réessaie.", "critical")
      return
    end
  end

  local l = {}
  l[#l + 1] = "Photos modifiées : " .. n_modifiees
  l[#l + 1] = "Photos ignorées : " .. (n_hors_format + n_hors_boitier)
    .. " (pas des 3FR : " .. n_hors_format .. " ; 3FR d'un autre boîtier que le X2D II : " .. n_hors_boitier .. ")"
  l[#l + 1] = "Photos en erreur : " .. #erreurs
  if n_modifiees > 0 then
    l[#l + 1] = ""
    l[#l + 1] = "Détail des photos modifiées :"
    for _, k in ipairs(ORDRE) do
      if par_cas[k] then l[#l + 1] = "  " .. par_cas[k] .. " x " .. LIBELLES[k] end
    end
    l[#l + 1] = ""
    l[#l + 1] = "Pour annuler : Édition > Annuler « " .. config.NOM_HISTORIQUE .. " »."
  end
  if #erreurs > 0 then
    l[#l + 1] = ""
    l[#l + 1] = "Erreurs (5 premières) :"
    for i = 1, math.min(5, #erreurs) do l[#l + 1] = "  " .. erreurs[i] end
  end
  LrDialogs.message("Réglages X2D II : résumé", table.concat(l, "\n"), #erreurs > 0 and "warning" or "info")
end)
