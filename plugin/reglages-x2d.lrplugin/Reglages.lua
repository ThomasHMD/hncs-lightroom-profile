-- Menu « Réglages du module » : chemin d'exiftool (enregistré dans les préférences du module).
local LrView = import "LrView"
local LrBinding = import "LrBinding"
local LrDialogs = import "LrDialogs"
local LrFunctionContext = import "LrFunctionContext"
local LrFileUtils = import "LrFileUtils"
local LrTasks = import "LrTasks"

local config = require("config")

LrTasks.startAsyncTask(function()
  LrFunctionContext.callWithContext("reglages-x2d", function(context)
    local f = LrView.osFactory()
    local props = LrBinding.makePropertyTable(context)
    props.exiftool = config.exiftool()

    local contenu = f:column {
      bind_to_object = props,
      spacing = f:control_spacing(),
      f:static_text { title = "Chemin d'exiftool (lecture des 3FR, jamais d'écriture)" },
      f:edit_field { value = LrView.bind("exiftool"), width_in_chars = 55 },
    }
    local r = LrDialogs.presentModalDialog { title = "Réglages X2D II", contents = contenu }
    if r == "ok" then
      config.definir_exiftool(props.exiftool)
      if LrFileUtils.exists(props.exiftool) ~= "file" then
        LrDialogs.message("Réglages X2D II", "Attention : aucun fichier à cet endroit :\n" .. props.exiftool, "warning")
      end
    end
  end)
end)
