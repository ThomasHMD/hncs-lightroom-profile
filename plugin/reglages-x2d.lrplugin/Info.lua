return {
  LrSdkVersion = 6.0,            -- applyDevelopSettings existe depuis la version 6.0 du SDK
  LrSdkMinimumVersion = 6.0,
  LrToolkitIdentifier = "com.thomashammoudi.reglages-x2d",
  LrPluginName = "Réglages X2D II (profil HNCS)",

  -- Bibliothèque > Modules externes, et Fichier > Modules externes
  LrLibraryMenuItems = {
    { title = "Appliquer profil et réglages X2D II", file = "AppliquerReglages.lua", enabledWhen = "photosSelected" },
    { title = "Réglages du module (chemin d'exiftool)", file = "Reglages.lua" },
  },
  LrExportMenuItems = {
    { title = "Appliquer profil et réglages X2D II", file = "AppliquerReglages.lua", enabledWhen = "photosSelected" },
    { title = "Réglages du module (chemin d'exiftool)", file = "Reglages.lua" },
  },

  VERSION = { major = 1, minor = 0, revision = 0, build = 1 },
}
