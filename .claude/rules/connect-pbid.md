Learnings from Claude about connecting to semantic models via the connect-pbid skill

- Store Desktop: `Start-Process archivo.pbip` abre una instancia en blanco; usar `PBIDesktopStore.exe "ruta.pbip"`. Con TMDL inválido abre en blanco sin aviso: validar antes con `TmdlSerializer.DeserializeDatabaseFromFolder`.
- TOM: DLL de `C:\Program Files\Microsoft SQL Server\170\DTS\Binn` solo con `[Reflection.Assembly]::LoadFrom` (Core, Tabular.Json, Tabular, en ese orden). ADOMD 17: `C:\Program Files\Microsoft.NET\ADOMD.NET\170`.
- Sin datos cargados, DMV/EVALUATE fallan ("needs at least one table"): catálogo con `GetSchemaDataSet("DBSCHEMA_CATALOGS")` y `ChangeDatabase`.
- Refresh TMSL (`{"refresh":{"type":"full"}}` vía `ExecuteNonQuery`) funciona para `File.Contents` sin credenciales. Medidas en vivo con `$model.SaveChanges()` sin cerrar Desktop; luego regenerar el TMDL para que disco y modelo coincidan.
- .ps1 con `ñ`: BOM UTF-8. Desde esta Bash el entorno supera 64 KB y `Add-Type` falla: `powershell.exe` con `env -i` y PATH mínimo; los scripts TOM van sin `env -i`.
- Ediciones externas del PBIP: barra «Aplicar cambios externos» + diálogo «Sobrescribir las ediciones no guardadas» (752×284). El primer clic en la barra solo deselecciona el visual activo: mandar Esc antes. En modo edición los botones se activan con Ctrl+clic.
- Capturar con `PrintWindow(hwnd, hdc, 2)` (sin foco) y recortar el lienzo localizando la banda de cabecera.
