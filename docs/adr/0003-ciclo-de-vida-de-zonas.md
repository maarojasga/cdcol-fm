# ADR 0003. Ciclo de vida de las zonas: los datos existen solo mientras se usan

**Estado:** aceptada (fase 0). Pedido de Ale, 9-oct-2026: pagar lo mínimo en nube.

## Decisión
Una zona tiene dos estados:

| Estado | Qué se conserva |
|---|---|
| `activa` | ARD, embeddings, índice ODC |
| `archivada` | `config/zonas/<zona>.yaml` y `config/manifiestos/<zona>.json`, en git |

- `cdcol archivar <zona>` escribe el manifiesto (ítems STAC fuente con checksum, `uv.lock`, commit, hash de pesos y de productos), lo deja en git y borra los productos de la zona. Pide confirmación.
- `cdcol reconstruir <zona>` usa exactamente los ítems del manifiesto y compara hashes (`Manifiesto.diferencias`). Si un ítem ya no existe en el proveedor, lo reporta en vez de reemplazarlo.
- Cada zona vive bajo su propio prefijo de almacenamiento (`zonas/<zona>/<producto>/<versión>/`), con una regla de expiración del bucket como respaldo.
- Las imágenes fuente (S1, S2) no se copian: se leen de los buckets públicos.

## Excepciones: nunca se borra
1. Lo usado en una decisión de crédito: almacenamiento frío, en el repositorio privado.
2. Lo publicado: Zenodo o Hugging Face, con DOI.
3. Los pesos de los adaptadores LoRA.

## Compromiso
Rehacer embeddings cuesta GPU. Por zona, `conservar_embeddings: true` los guarda en frío. Por defecto, `false`.
