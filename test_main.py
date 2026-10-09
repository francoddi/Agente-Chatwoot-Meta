import unittest
from unittest.mock import AsyncMock, patch

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

    def test_dos_burbujas_del_mismo_seguimiento_cuentan_una(self):
        messages = [
            _mensaje(1, 1, "primera", metadata=_metadata_seguimiento(1)),
            _mensaje(2, 1, "segunda", metadata=_metadata_seguimiento(1)),
            _mensaje(3, 1, "otro", metadata=_metadata_seguimiento(2)),
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
            patch.object(main, "get_conversation_labels", AsyncMock(return_value=[])),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()

    async def test_envia_primero_y_segundo_con_secuencia_persistente(self):
        base = [
            _mensaje(1, 1, "pasame tu localidad y dirección"),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta el código postal"),
        ]
        send = AsyncMock()
        with (
            patch.object(main, "get_conversation_labels", AsyncMock(return_value=[])),
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
            _mensaje(6, 1, "ahora me falta la foto del DNI"),
        ]
        send.reset_mock()
        with (
            patch.object(main, "get_conversation_labels", AsyncMock(return_value=[])),
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
            _mensaje(7, 1, "perfecto, me falta el DNI"),
        ]
        with (
            patch.object(main, "get_conversation_labels", AsyncMock(return_value=[])),
            patch.object(main, "_fetch_conversation_messages", AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter", AsyncMock()) as openrouter,
        ):
            await main.send_followup_if_needed(10, 2700)
        openrouter.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
