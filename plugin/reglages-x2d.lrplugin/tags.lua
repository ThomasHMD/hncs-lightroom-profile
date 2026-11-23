--[[
  tags.lua : lecture des tags d'un lot de 3FR avec UN SEUL appel d'exiftool (lecture seule), SANS API Lightroom.

  Les opérations système (écrire / lire un fichier, lancer une commande) sont passées dans `sys`, pour que le même
  code tourne dans Lightroom (LrTasks.execute, LrPathUtils) et dans les tests (os.execute, io). `sys` contient :
    sys.ecrire(chemin, texte)   sys.lire(chemin) -> texte ou nil   sys.executer(commande) -> code de sortie
    sys.fichier_temporaire(suffixe) -> chemin   sys.supprimer(chemin)

  Tags lus : ISO, IFD0:BaselineExposure, makernotes 0x007a / 0x007b /
  0x007c (ombres, hautes lumières, autoknee) et Make / Model pour reconnaître le X2D II.
]]

local regle = require("regle")

local M = {}

M.EXIFTOOL_DEFAUT = "/opt/homebrew/bin/exiftool"

local SEP = "\t"

-- Contenu du fichier d'arguments d'exiftool (un argument par ligne). Aucun risque de guillemets dans les chemins.
function M.argfile(chemins)
  local l = {
    "-charset", "filename=utf8",
    "-q",                      -- pas de ligne « 2 image files read »
    "-n",                      -- valeurs numériques brutes
    "-f",                      -- tag absent -> "-"
    "-u",                      -- tags inconnus (makernotes 0x007a...)
    "-p",
    table.concat({
      "$Directory/$FileName", "$Make", "$Model", "$ISO", "${IFD0:BaselineExposure}",
      "${MakerUnknown:Unknown_0x007a}", "${MakerUnknown:Unknown_0x007b}", "${MakerUnknown:Unknown_0x007c}",
    }, SEP),
  }
  for _, c in ipairs(chemins) do l[#l + 1] = c end
  return table.concat(l, "\n") .. "\n"
end

local function nombre(s)
  if s == nil or s == "-" or s == "" then return nil end
  return tonumber(s)
end

--[[
  Analyse la sortie d'exiftool. Retourne une table chemin -> { fichier, make, model, iso, be, sd, hl, kn } (bruts :
  nil = tag absent). `be` absent -> nil (la normalisation le met à 0.0).
]]
function M.analyser(texte)
  local out = {}
  for ligne in (texte or ""):gmatch("[^\r\n]+") do
    local champs = {}
    local pos = 1
    while true do
      local i = ligne:find(SEP, pos, true)
      if not i then
        champs[#champs + 1] = ligne:sub(pos)
        break
      end
      champs[#champs + 1] = ligne:sub(pos, i - 1)
      pos = i + 1
    end
    if #champs >= 8 then
      out[champs[1]] = {
        fichier = champs[1],
        make = champs[2], model = champs[3],
        iso = nombre(champs[4]), be = nombre(champs[5]),
        sd = nombre(champs[6]), hl = nombre(champs[7]), kn = nombre(champs[8]),
      }
    end
  end
  return out
end

-- Le boîtier est-il un X2D II ? (« Hasselblad » + « X2D II » dans le modèle ; le X2D 100C d'origine est exclu.)
function M.est_x2d2(t)
  local make = (t.make or ""):lower()
  local model = (t.model or ""):upper()
  return make:find("hasselblad", 1, true) ~= nil and model:find("X2D II", 1, true) ~= nil
end

local function guillemets(s)
  return "'" .. s:gsub("'", "'\\''") .. "'"
end

--[[
  Lit les tags de tous les `chemins` en un seul appel. Retourne (table chemin -> tags bruts, nil) ou (nil, message).
]]
function M.lire(chemins, exiftool, sys)
  exiftool = exiftool or M.EXIFTOOL_DEFAUT
  local args = sys.fichier_temporaire(".args")
  local sortie = sys.fichier_temporaire(".txt")
  local erreurs = sys.fichier_temporaire(".err")
  sys.ecrire(args, M.argfile(chemins))
  local commande = guillemets(exiftool) .. " -@ " .. guillemets(args)
    .. " > " .. guillemets(sortie) .. " 2> " .. guillemets(erreurs)
  local code = sys.executer(commande)
  local texte = sys.lire(sortie)
  local err = sys.lire(erreurs)
  sys.supprimer(args); sys.supprimer(sortie); sys.supprimer(erreurs)
  -- exiftool rend 1 quand un fichier est introuvable mais lit les autres : seule une sortie vide est fatale.
  if texte == nil or texte == "" then
    if code ~= 0 and code ~= 1 then
      return nil, "exiftool introuvable ou en échec (code " .. tostring(code) .. ") : " .. tostring(exiftool)
    end
    return nil, "exiftool n'a rien lu" .. ((err and err ~= "") and (" : " .. err:sub(1, 200)) or "")
  end
  return M.analyser(texte), nil
end

-- Tags normalisés à partir des tags bruts.
function M.normalises(brut)
  return regle.normaliser(brut)
end

return M
