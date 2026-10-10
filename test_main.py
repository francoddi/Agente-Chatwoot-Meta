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


def _metadata_bot(followup_closed=False):
    return {
        "data": {
            main.FOLLOWUP_METADATA_KEY: {
                "kind": "bot_reply",
                "followup_closed": followup_closed,
            }
        }
    }


def _conversacion_activa(**overrides):
    data = {"labels": [], "status": "open", "can_reply": True}
    data.update(overrides)
    return data


class ReglasDeNegocioTest(unittest.TestCase):
    def test_precios_consumidor_final_estan_al_65_por_ciento(self):
        movistar_tuenti = main.SYSTEM_PROMPT.split(
            "28. CONSUMIDOR FINAL — MOVISTAR / TUENTI", 1
        )[1].split("29. EMPRESA — MOVISTAR / TUENTI", 1)[0]
        personal = main.SYSTEM_PROMPT.split(
            "31. CONSUMIDOR FINAL — PERSONAL", 1
        )[1].split("32. CONSUMIDOR FINAL — LÍNEA NUEVA", 1)[0]
        tabla_65 = (
            "4 GB → $20.997",
            "7 GB → $23.870",
            "10 GB → $30.345",
            "30 GB → $40.460",
            "50 GB → $46.529",
        )

        for seccion in (movistar_tuenti, personal):
            self.assertIn("65% OFF", seccion)
            for precio in tabla_65:
                self.assertIn(precio, seccion)

        self.assertNotIn("70% OFF", movistar_tuenti)
        self.assertNotIn("70% OFF", personal)

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
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "**Análisis de la conversación**\nEl cliente ya pasó todos los datos."
        ))
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "<analysis>Debo decidir qué contestar</analysis> hola"
        ))
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "1. Analizar el mensaje del cliente\n2. Preparar la respuesta"
        ))
        self.assertTrue(main._tiene_razonamiento_filtrado(
            "mandale ese mensaje y esperá.\n\n[INTERNAL_NOTE]"
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

    def test_bloquea_repreguntar_compania_ya_informada(self):
        historial = [
            _mensaje(1, 0, "Hola, quiero pasarme a Claro"),
            _mensaje(2, 1, "de qué compañía sos?"),
            _mensaje(3, 0, "Movistar"),
            _mensaje(4, 1, "te paso los planes"),
            _mensaje(5, 0, "Hola, quiero pasarme a Claro"),
        ]
        motivo = main._motivo_respuesta_incoherente(
            "hola, soy Valentina. en qué compañía estás ahora?", historial
        )
        self.assertIn("volvió a preguntar", motivo)
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "hola de nuevo, te habían interesado estos planes?", historial
        ))
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "como ya sé cuál es tu compañía, seguimos con los planes de Movistar", historial
        ))
        variantes = [
            "con cuál compañía estás ahora?",
            "cuál es tu empresa actual?",
            "tu línea de qué compañía es?",
            "sos de Movistar, Personal o Tuenti?",
        ]
        for respuesta in variantes:
            with self.subTest(respuesta=respuesta):
                self.assertIsNotNone(
                    main._motivo_respuesta_incoherente(respuesta, historial)
                )

    def test_permite_preguntar_compania_de_una_segunda_linea(self):
        historial = [
            _mensaje(1, 0, "soy de Movistar"),
            _mensaje(2, 1, "cuál plan te interesa?"),
            _mensaje(3, 0, "también quiero agregar otra línea"),
        ]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "la otra línea de qué compañía es?", historial
        ))

    def test_responde_ubicacion_solo_con_mar_del_plata(self):
        historial = [
            _mensaje(1, 1, "en qué compañía estás?"),
            _mensaje(2, 0, "De donde son"),
        ]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "somos de Mar del Plata", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "trabajamos con Celtafone, agente oficial de Claro", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "trabajamos de forma online en todo el país", historial
        ))

    def test_responde_identidad_con_agentes_oficiales_de_claro(self):
        historial = [_mensaje(1, 0, "Quienes son ustedes?")]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "somos agentes oficiales de Claro", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "somos de Mar del Plata", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "somos Celtafone, agente oficial de Claro", historial
        ))

    def test_responde_juntas_ubicacion_e_identidad(self):
        historial = [_mensaje(1, 0, "¿De dónde son y quiénes son ustedes?")]
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "somos de Mar del Plata y somos agentes oficiales de Claro", historial
        ))

    def test_bloquea_precio_empresa_sin_compania(self):
        historial = [_mensaje(1, 0, "la línea es de una empresa, con CUIT")]
        self.assertIn(
            "precio de Empresa",
            main._motivo_respuesta_incoherente(
                "por ejemplo el de 30gb te queda en $27.735", historial
            ),
        )
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "decime primero en qué compañía está la línea", historial
        ))
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "el plan de 30gb queda en 27.735 pesos por mes", historial
        ))

    def test_bloquea_afirmaciones_comerciales_no_verificadas(self):
        historial = [_mensaje(1, 0, "tengo una duda")]
        casos = [
            "los aumentos los va regulando el gobierno",
            "podés pedir que te cambien la fecha de vencimiento",
            "quedate tranquila, no es una estafa",
            "quedate tranquila que esto no es ninguna estafa",
            "es 100% seguro",
            "es totalmente seguro",
            "es el procedimiento oficial",
            "la foto es solo para validar los datos",
            "como no tenés deuda eso agiliza el cambio",
            "el roaming en Chile funciona como si estuvieras en Argentina, sin pagar extra",
            "tus contactos nunca se pierden, siempre quedan guardados",
            "en diciembre seguro te aumenta bastante",
            "si la das de baja perdés el número para siempre",
            "tus datos no se comparten con nadie más",
        ]
        for texto in casos:
            with self.subTest(texto=texto):
                self.assertIsNotNone(main._motivo_respuesta_incoherente(texto, historial))
        respuestas_seguras = [
            "no puedo confirmarte si se puede cambiar el vencimiento",
            "podés verificarlo por los medios oficiales de Claro antes de seguir",
            "trabajamos con Celtafone, agente oficial de Claro",
            "somos agentes oficiales de Claro",
            "los aumentos futuros los define la compañía y no puedo anticipar una fecha",
        ]
        for texto in respuestas_seguras:
            with self.subTest(texto=texto):
                self.assertIsNone(main._motivo_respuesta_incoherente(texto, historial))

    def test_bloquea_aceptar_un_email_invalido_en_el_turno_actual(self):
        historial = [
            _mensaje(1, 1, "pasame tu email"),
            _mensaje(2, 0, "arevalodavid@120.con"),
        ]
        self.assertIsNotNone(main._motivo_respuesta_incoherente(
            "listo, lo anoto. ahora pasame tu localidad", historial
        ))
        self.assertIsNone(main._motivo_respuesta_incoherente(
            "ese email parece tener un error, me lo revisás?", historial
        ))

    def test_normaliza_o_descarta_emails_antes_de_sheets(self):
        self.assertEqual(main._normalizar_email_ficha("juan@gmail.con"), "juan@gmail.com")
        self.assertEqual(main._normalizar_email_ficha("ventas@empresa.com.ar"), "ventas@empresa.com.ar")
        self.assertEqual(main._normalizar_email_ficha("arevalodavid@120.con"), "")
        campos = main._parse_ficha_fields("Nombre: Juan\nEmail: arevalodavid@120.con")
        self.assertNotIn("Email", campos)

    def test_un_pedido_visible_no_puede_cerrar_seguimientos(self):
        pendientes = [
            "dale, espero las fotos y con eso cerramos todo",
            "me falta el código postal",
            "cuando puedas mandame el dorso del DNI",
            "te sirve ese plan?",
        ]
        for texto in pendientes:
            with self.subTest(texto=texto):
                self.assertTrue(main._respuesta_deja_algo_pendiente(texto))
        self.assertFalse(main._respuesta_deja_algo_pendiente(
            "no hay problema, cualquier cosa me escribís. que andes bien"
        ))

    def test_detecta_reloj_de_followup_perdido_por_redeploy(self):
        ahora = 1_000_000
        last = _mensaje(
            9,
            1,
            "dale, espero las fotos",
            metadata=_metadata_bot(),
        )
        last["created_at"] = ahora - main.FOLLOWUP_DELAY_MIN_SECONDS - 60
        conversation = _conversacion_activa(
            id=92,
            last_non_activity_message=last,
        )
        self.assertTrue(main._es_candidata_followup_recuperado(conversation, ahora))
        last["content_attributes"] = _metadata_bot(followup_closed=True)
        self.assertFalse(main._es_candidata_followup_recuperado(conversation, ahora))

    def test_no_habilita_seguimiento_por_audio_ilegible_o_pedido_de_tiempo(self):
        solo_audio = [
            _mensaje(1, 1, "el número que querés pasar, en qué compañía está?"),
            _mensaje(2, 0, attachments=[{"file_type": "audio", "extension": "ogg"}]),
            _mensaje(3, 1, "no puedo escuchar el audio, escribímelo por favor"),
        ]
        self.assertFalse(main._cliente_confirmo_plan(solo_audio))
        self.assertFalse(main._cliente_ya_paso_datos(solo_audio))

        pide_tiempo = [
            _mensaje(1, 1, "pasame nombre completo, DNI y número a portar"),
            _mensaje(2, 0, "me das un rato por favor"),
            _mensaje(3, 1, "dale, avisame cuando los tengas"),
        ]
        self.assertTrue(main._cliente_confirmo_plan(pide_tiempo))
        self.assertFalse(main._cliente_ya_paso_datos(pide_tiempo))

    def test_neutraliza_formulas_en_campos_de_sheets(self):
        self.assertEqual(main._valor_seguro_sheets("=IMPORTXML(A1)"), "'=IMPORTXML(A1)")
        self.assertEqual(main._valor_seguro_sheets("+5492230000000"), "'+5492230000000")
        self.assertEqual(main._valor_seguro_sheets("Mar del Plata"), "Mar del Plata")

    def test_imagenes_comerciales_previas_no_cuentan_como_dni(self):
        messages = [
            _mensaje(1, 0, "mirá mi factura", attachments=[_imagen("factura", 10)]),
            _mensaje(2, 1, "te paso los planes"),
            _mensaje(3, 0, "quiero el de 4gb"),
            _mensaje(4, 1, "pasame nombre completo, DNI y fotos frente y dorso"),
            _mensaje(5, 0, attachments=[_imagen("dni-frente", 11)]),
        ]
        candidatos = main._adjuntos_candidatos_dni(messages)
        self.assertEqual([item["_dni_url"] for item in candidatos], ["dni-frente"])


class ProteccionesAsincronicasTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_duplica_el_mismo_aviso_de_falla_en_una_hora(self):
        main._fallos_respuesta_avisados.clear()
        send = AsyncMock()
        with (
            patch.object(main, "NUMERO_DUENO", "+5490000000000"),
            patch.object(main, "_get_contact_phone", AsyncMock(return_value="+5491111111111")),
            patch.object(main, "_find_conversation_by_phone", AsyncMock(return_value=99)),
            patch.object(main, "send_message", send),
        ):
            await main._avisar_fallo_respuesta(80, "mismo error")
            await main._avisar_fallo_respuesta(80, "mismo error")
        send.assert_awaited_once()
        main._fallos_respuesta_avisados.clear()

    async def test_openrouter_reintenta_si_devuelve_solo_espacios(self):
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = [
            {"choices": [{"message": {"content": "  \n  "}, "finish_reason": "stop"}]},
            {"choices": [{"message": {"content": "respuesta válida"}, "finish_reason": "stop"}]},
        ]
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(main.httpx, "AsyncClient", return_value=context):
            respuesta = await main.call_openrouter(
                [{"role": "user", "content": "hola"}], intentos=2
            )
        self.assertEqual(respuesta, "respuesta válida")
        self.assertEqual(client.post.await_count, 2)

    async def test_openrouter_no_reintenta_contenido_bloqueado(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "error": {"code": "PROHIBITED_CONTENT", "message": "blocked by safety policy"}
        }
        client = AsyncMock()
        client.post.return_value = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        with patch.object(main.httpx, "AsyncClient", return_value=context):
            with self.assertRaises(main.OpenRouterContenidoBloqueadoError):
                await main.call_openrouter([{"role": "user", "content": "imagen"}], intentos=3)
        self.assertEqual(client.post.await_count, 1)

    async def test_regenera_una_respuesta_comercial_incoherente(self):
        historial = [_mensaje(1, 0, "soy de Movistar")]
        with patch.object(
            main,
            "call_openrouter",
            AsyncMock(side_effect=[
                "hola, en qué compañía estás?",
                "seguimos con Movistar, cuál plan te interesa?",
            ]),
        ) as openrouter:
            respuesta = await main._call_openrouter_respuesta_cliente(
                [{"role": "system", "content": "prueba"}], historial
            )
        self.assertEqual(respuesta, "seguimos con Movistar, cuál plan te interesa?")
        self.assertEqual(openrouter.await_count, 2)

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

    async def test_falla_de_sheets_no_avisa_a_camila_ni_etiqueta_ddd(self):
        notify = AsyncMock()
        label = AsyncMock()
        with (
            patch.object(main, "_verificar_fotos_dni",
                         AsyncMock(return_value=("frente", "dorso"))),
            patch.object(main, "_get_contact_phone", AsyncMock(return_value="+5492200000000")),
            patch.object(main, "log_to_google_sheets", AsyncMock(return_value=False)),
            patch.object(main, "notify_camila_carga_sheets", notify),
            patch.object(main, "add_conversation_label", label),
        ):
            with self.assertRaisesRegex(RuntimeError, "Google Sheets"):
                await main._registrar_derivacion_completa(
                    12,
                    {"Nombre": "Prueba", "Compañía actual": "Movistar"},
                    [],
                )
        notify.assert_not_awaited()
        label.assert_not_awaited()

    async def test_verifica_dos_caras_y_acepta_dni_digital_en_un_adjunto(self):
        mensajes_dos = [
            _mensaje(1, 1, "pasame foto del frente y dorso del DNI"),
            _mensaje(2, 0, attachments=[
                _imagen("dni-frente-unico", 101),
                _imagen("dni-dorso-unico", 102),
            ]),
        ]
        main._dni_verification_cache.clear()
        with (
            patch.object(main, "download_attachment",
                         AsyncMock(return_value=(b"imagen", "image/jpeg"))),
            patch.object(main, "call_openrouter",
                         AsyncMock(return_value="COMPLETO FRENTE=1 DORSO=2")),
        ):
            self.assertEqual(
                await main._verificar_fotos_dni(mensajes_dos),
                ("dni-frente-unico", "dni-dorso-unico"),
            )

        mensajes_digital = [
            _mensaje(1, 1, "pasame una foto del DNI"),
            _mensaje(2, 0, "DNI digital de Mi Argentina",
                     attachments=[_imagen("dni-digital-ambas", 103)]),
        ]
        main._dni_verification_cache.clear()
        with (
            patch.object(main, "download_attachment",
                         AsyncMock(return_value=(b"imagen", "image/jpeg"))),
            patch.object(main, "call_openrouter", AsyncMock(return_value="COMPLETO AMBAS=1")),
        ):
            self.assertEqual(
                await main._verificar_fotos_dni(mensajes_digital),
                ("dni-digital-ambas", "dni-digital-ambas"),
            )

    async def test_build_message_content_entrega_todos_los_adjuntos_al_modelo(self):
        mensaje = _mensaje(1, 0, "frente y dorso", attachments=[
            _imagen("frente-lote", 201),
            _imagen("dorso-lote", 202),
        ])
        with patch.object(
            main,
            "build_image_content",
            AsyncMock(side_effect=[
                [{"type": "image_url", "image_url": {"url": "frente"}}],
                [{"type": "image_url", "image_url": {"url": "dorso"}}],
            ]),
        ) as build:
            contenido, tipo = await main.build_message_content(mensaje)
        self.assertEqual(build.await_count, 2)
        self.assertEqual(tipo, "documents")
        self.assertEqual(len(contenido), 2)

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

    async def test_no_sigue_si_la_ultima_respuesta_cerro_followups(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad y dirección", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "gracias, que andes bien", metadata=_metadata_bot(True)),
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

    async def test_reintenta_envio_de_seguimiento_sin_duplicar(self):
        messages = [
            _mensaje(1, 1, "pasame tu localidad", metadata=_metadata_bot()),
            _mensaje(2, 0, "Rosario"),
            _mensaje(3, 1, "me falta la dirección", metadata=_metadata_bot()),
        ]
        send = AsyncMock(side_effect=[RuntimeError("timeout"), None])
        with (
            patch.object(main, "_get_conversation_for_followup",
                         AsyncMock(return_value=_conversacion_activa())),
            patch.object(main, "_fetch_conversation_messages",
                         AsyncMock(return_value=messages)),
            patch.object(main, "call_openrouter",
                         AsyncMock(return_value="me pasás la dirección?")),
            patch.object(main, "send_message", send),
            patch.object(main.asyncio, "sleep", AsyncMock()),
            patch.object(main, "_avisar_fallo_respuesta", AsyncMock()) as aviso,
        ):
            await main.send_followup_if_needed(10, 2700)
        self.assertEqual(send.await_count, 2)
        aviso.assert_not_awaited()

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
