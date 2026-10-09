import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import main


def _mensaje(message_id, message_type, content="", attachments=None, metadata=None):
    return {
        "id": message_id,
        "message_type": message_type,
        "content": content,
        "attachments": attachments or [],
        "content_attributes": metadata or {},
        "private": False,
    }


def _imagen(url, size, width=1000, height=600):
    return {
        "file_type": "image",
        "data_url": url,
        "file_size": size,
        "width": width,
        "height": height,
    }


def _metadata_seguimiento(sequence):
    return {
        "data": {
            main.FOLLOWUP_METADATA_KEY: {
                "kind": "followup",
                "sequence": sequence,
            }
        }
    }


def _metadata_bot():
    return {
        "data": {
            main.FOLLOWUP_METADATA_KEY: {
                "kind": "bot_reply",
            }
        }
    }


def _conversacion_activa(**overrides):
    data = {"labels": [], "status": "open", "can_reply": True}
    data.update(overrides)
    return data


class ReglasDeNegocioTest(unittest.TestCase):
    def test_solo_pedir_datos_no_habilita_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame nombre completo, localidad y dirección"),
            _mensaje(2, 0, "dale"),
        ]
        self.assertFalse(main._cliente_ya_paso_datos(messages))

    def test_un_dato_del_cliente_habilita_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame nombre completo, localidad y dirección"),
            _mensaje(2, 0, "Mar del Plata"),
        ]
        self.assertTrue(main._cliente_ya_paso_datos(messages))

    def test_explicar_portabilidad_no_equivale_a_iniciar_checklist(self):
        messages = [
            _mensaje(1, 1, "podés portar tu línea manteniendo el mismo número"),
            _mensaje(2, 0, "quiero el de 30 GB"),
        ]
        self.assertFalse(main._cliente_ya_paso_datos(messages))

    def test_dato_proactivo_tambien_habilita_seguimiento(self):
        self.assertTrue(main._cliente_ya_paso_datos([
            _mensaje(1, 0, "mi DNI es 12345678"),
            _mensaje(2, 1, "perfecto, qué localidad es?", metadata=_metadata_bot()),
        ]))
        self.assertTrue(main._cliente_ya_paso_datos([
            _mensaje(1, 0, "mi email: cliente@ejemplo.com"),
        ]))

    def test_webhook_duplicado_se_detecta_sin_reprocesarlo(self):
        message_id = "prueba-duplicado-999"
        main._seen_incoming_message_ids.pop(message_id, None)
        self.assertTrue(main._registrar_webhook_entrante(message_id))
        self.assertFalse(main._registrar_webhook_entrante(message_id))
        main._seen_incoming_message_ids.pop(message_id, None)

    def test_dos_burbujas_del_mismo_seguimiento_cuentan_una(self):
        messages = [
            _mensaje(1, 1, "primera", metadata=_metadata_seguimiento(1)),
            _mensaje(2, 1, "segunda", metadata=_metadata_seguimiento(1)),
            _mensaje(3, 1, "otro", metadata=_metadata_seguimiento(2)),
        ]
        self.assertEqual(main._followups_enviados(messages), 2)

    def test_secuencia_dos_sola_igual_bloquea_un_tercero(self):
        messages = [
            _mensaje(3, 1, "segundo", metadata=_metadata_seguimiento(2)),
        ]
        self.assertEqual(main._followups_enviados(messages), 2)

    def test_estado_de_fotos_exige_dos_imagenes_distintas(self):
        una = [_mensaje(1, 0, attachments=[_imagen("frente", 100)])]
        repetida = [
            _mensaje(1, 0, attachments=[_imagen("frente", 100)]),
            _mensaje(2, 0, attachments=[_imagen("frente-reenviado", 100)]),
        ]
        dos = repetida + [_mensaje(3, 0, attachments=[_imagen("dorso", 200)])]
        self.assertEqual(main._estado_fotos_dni([]), 0)
        self.assertEqual(main._estado_fotos_dni(una), 1)
        self.assertEqual(main._estado_fotos_dni(repetida), 1)
        self.assertEqual(main._estado_fotos_dni(dos), 2)

    def test_un_pdf_cuenta_como_frente_y_dorso(self):
        pdf = {
            "file_type": "file",
            "extension": "pdf",
            "data_url": "dni.pdf",
        }
        self.assertEqual(main._estado_fotos_dni([_mensaje(1, 0, attachments=[pdf])]), 2)

    def test_filtra_el_razonamiento_interno_observado(self):
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "**Validating Current Status**\nThe user has supplied the information."
        ))
        self.assertFalse(main._tiene_razonamiento_filtrado(
            "perfecto, me falta solamente la foto del dorso"
        ))

    def test_filtra_respuestas_en_ingles_aunque_no_parezcan_razonamiento(self):
        casos = [
            "Hello! How can I help you today?",
            "The customer has already sent the required data.",
            "Please send the front and back photos.",
            "Thanks!",
            "Great choice! Everything looks perfect.",
            "I can help you with that.",
            "perfecto, please mandame la otra foto",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertTrue(main._tiene_razonamiento_filtrado(texto))

    def test_no_bloquea_anglicismos_normales_dentro_del_espanol(self):
        casos = [
            "te paso el link de WhatsApp",
            "me falta tu email para completar los datos",
            "el plan incluye 30 GB de internet",
            "podés abrir la app de Claro?",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertFalse(main._tiene_razonamiento_filtrado(texto))


class ProteccionesAsincronicasTest(unittest.IsolatedAsyncioTestCase):
    async def test_mensaje_normal_del_bot_lleva_marca_interna(self):
        client = AsyncMock()
        response = MagicMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(main.httpx, "AsyncClient", return_value=context):
            await main.send_message(10, "respuesta normal")
        body = client.post.await_args.kwargs["json"]
        self.assertEqual(
            body["content_attributes"]["data"][main.FOLLOWUP_METADATA_KEY]["kind"],
            "bot_reply",
        )

    async def test_registro_sin_fotos_se_bloquea_antes_de_sheets(self):
        with self.assertRaises(main.FotosDNIIncompletasError):
            await main._registrar_derivacion_completa(12, {"Nombre": "Adán"}, [])

    async def test_no_encadena_seguimiento_sobre_otro_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad y dirección"),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "te quedó alguna duda?", metadata=_metadata_seguimiento(1)),
        ]
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_envia_primero_y_segundo_con_secuencia_persistente(self):
        base = [
            _mensaje(1, 1, "pasame tu localidad y dirección"),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta el código postal", metadata=_metadata_bot()),
        ]
        send = AsyncMock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=base)),
            patch.object(main, "call_openrouter", AsyncMock(return_value="me pasás el código postal?")),
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        metadata_1 = send.await_args.kwargs["content_attributes"]
        self.assertEqual(
            metadata_1["data"][main.FOLLOWUP_METADATA_KEY]["sequence"], 1
        )

        con_primero_y_respuesta = base + [
            _mensaje(4, 1, "seguimiento uno", metadata=_metadata_seguimiento(1)),
            _mensaje(5, 0, "2000"),
            _mensaje(6, 1, "ahora me falta la foto del DNI", metadata=_metadata_bot()),
        ]
        send.reset_mock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages",
                         AsyncMock(return_value=con_primero_y_respuesta)),
            patch.object(main, "call_openrouter", AsyncMock(return_value="me mandás las fotos?")),
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        metadata_2 = send.await_args.kwargs["content_attributes"]
        self.assertEqual(
            metadata_2["data"][main.FOLLOWUP_METADATA_KEY]["sequence"], 2
        )

    async def test_bloquea_un_tercer_seguimiento_aunque_el_cliente_haya_respondido(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad y dirección"),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "seguimiento uno", metadata=_metadata_seguimiento(1)),
            _mensaje(4, 0, "Córdoba 123"),
            _mensaje(5, 1, "seguimiento dos", metadata=_metadata_seguimiento(2)),
            _mensaje(6, 0, "mi código postal es 2000"),
            _mensaje(7, 1, "perfecto, me falta el DNI", metadata=_metadata_bot()),
        ]
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_no_sigue_despues_de_un_mensaje_manual(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad y dirección", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "hola, tomo yo la conversación"),  # sin metadato = humano
        ]
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_no_sigue_una_conversacion_resuelta(self):
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa(status="resolved"))),
            patch.object(main, "_fetch_conversation_messages", AsyncMock()) as fetch,
        ):
            await main.send_followup_if_needed(10, 2700)
        fetch.assert_not_awaited()

    async def test_no_sigue_si_chatwoot_no_permite_responder(self):
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa(can_reply=False))),
            patch.object(main, "_fetch_conversation_messages", AsyncMock()) as fetch,
        ):
            await main.send_followup_if_needed(10, 2700)
        fetch.assert_not_awaited()

    async def test_no_sigue_si_el_cliente_ya_respondio(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
            _mensaje(4, 0, "calle Córdoba 123"),
        ]
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_varias_burbujas_se_envian_como_un_solo_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
        ]
        send = AsyncMock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter",
                         AsyncMock(return_value="me pasás la calle?\n---\ny la altura?")),
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[1], "me pasás la calle?\n\ny la altura?")

    async def test_no_permite_derivar_desde_un_seguimiento(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
        ]
        respuesta_mala = f"escribile a Camila: {main.NUMERO_CAMILA}"
        send = AsyncMock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock(return_value=respuesta_mala)) as openrouter,
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        self.assertEqual(openrouter.await_count, 2)
        send.assert_not_awaited()

    async def test_cancela_si_un_humano_responde_mientras_se_redacta(self):
        antes = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
        ]
        despues = antes + [_mensaje(4, 1, "hola, sigo yo desde acá")]
        send = AsyncMock()
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages",
                         AsyncMock(side_effect=[antes, despues])),
            patch.object(main, "call_openrouter", AsyncMock(return_value="me pasás la calle?")),
            patch.object(main, "send_message", send),
        ):
            await main.send_followup_if_needed(10, 2700)
        send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
