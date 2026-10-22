# Seguimiento de posiciones (uso privado)

Funcionalidad opcional y **local**. Ningún dato de posiciones, saldos ni notas se exporta
a la demo pública ni a `exportar_powerbi.py`.

## Archivo `output/posiciones.csv`

Columnas (ver `posiciones.example.csv`):

| Columna | Requerida | Validación |
|---|---|---|
| `ticker` | sí | símbolo del radar en mayúsculas, ej. `BTCUSDT` |
| `fecha_compra` | sí | `AAAA-MM-DD` (o con hora), no futura |
| `precio_compra` | sí | número finito > 0, con **punto** decimal |
| `cantidad` | sí | número finito > 0 |
| `stop_loss_pct` | no | > 0 y < 100 |
| `take_profit_pct` | no | > 0 y ≤ 1000 |
| `trailing_pct` | no | > 0 y < 100 |
| `notas` | no | texto libre (se escapa en los mensajes) |

- **Clave estable:** `ticker + fecha_compra + precio_compra` (precio normalizado).
- **Editar** `cantidad`, porcentajes o `notas` de una fila existente **actualiza** la posición
  abierta. Si la posición ya está cerrada, no se modifica y se informa.
- **Cambiar** `ticker`, `fecha_compra` o `precio_compra` crea otra posición: la anterior queda
  abierta y se informa como "ya no figura en el CSV" (cerrala con el comando de abajo).
- Filas inválidas: se informan con número de línea y campo (sin mostrar valores) y no se
  importan. Filas duplicadas y columnas desconocidas también se informan.
- Una fila cuyas notas empiezan con `Compra de ejemplo` se ignora (y se cuenta).

## Gatillos: una alerta por evento

Se evalúa contra el último **cierre válido** del radar (dato `valido`, no obsoleto).
Prioridad si se cumplen varias condiciones: take profit > trailing > stop loss.

1. Cuando un gatillo (posición + tipo) se cumple por primera vez, se registra **un** evento
   en `eventos_posicion` con `notificado = 0`.
2. Mientras ese evento esté vigente (no rearmado), las corridas siguientes **no** crean otro
   registro ni otra alerta, aunque el precio siga del otro lado del umbral.
3. La notificación se intenta en cada corrida hasta que Telegram confirme el envío
   (`notificado = 1`); cada intento suma `intentos_notificacion`.
4. El radar **nunca cierra** una posición.

Decisiones explícitas:

```bash
python gestionar_posiciones.py gatillos                  # avisos vigentes
python gestionar_posiciones.py confirmar 12              # "lo vi" (no rearma)
python gestionar_posiciones.py rearmar 12                # vuelve a vigilar ese gatillo
python gestionar_posiciones.py cerrar 3 --precio 61000   # cerrás vos, con tu precio real
```

Migración: al actualizar, los eventos históricos se marcan como notificados y quedan
vigentes, así que una posición que antes repetía la misma alerta cada hora deja de hacerlo.
Si querés volver a vigilarla, rearmá su último evento.

## Ripio (solo lectura)

Estados por moneda: `con_saldo`, `bajo_umbral` (polvo), `cero_confirmado`, `dato_invalido`,
y moneda **ausente** de la respuesta. Solo `cero_confirmado` produce "posible venta total";
un saldo bajo el umbral, un saldo bloqueado (se suma al disponible), una moneda ausente o
una consulta fallida **nunca** se interpretan como venta. Cada cambio se registra una vez y
se notifica con el mismo esquema de reintentos.
