--!nonstrict
-- Servicio auxiliar del plugin Notes.
--
-- El panel es una entrada que solo existe mientras el panel está abierto, así
-- que este servicio (siempre vivo mientras el plugin está habilitado) hace de
-- puente para que otras herramientas puedan controlarlo por IPC:
--
--   noctalia msg plugin faminec/notes:service all refresh
--   noctalia msg plugin faminec/notes:service all open-note "mi nota.md"
--
-- `refresh` incrementa `notes_bump`, la misma señal que usa el lanzador, de
-- modo que el panel abierto recoge al instante los cambios hechos fuera
-- (app móvil, sincronización, editor de texto...).
--
-- `open-note` deja apuntada una nota para que el panel la abra en cuanto se
-- abra (`noctalia msg panel-open faminec/notes:panel`).

local function bumpNotesState()
  local bump = noctalia.state.get("notes_bump")
  noctalia.state.set("notes_bump", (type(bump) == "number" and bump or 0) + 1)
end

function onIpc(event, payload)
  if event == "refresh" then
    bumpNotesState()
    return
  end
  if event == "open-note" then
    if type(payload) == "string" and payload ~= "" then
      noctalia.state.set("open_note", payload)
      noctalia.state.set("open_home", false)
    end
    return
  end
  if event == "open-home" then
    noctalia.state.set("open_home", true)
    noctalia.state.set("open_note", "")
  end
end
