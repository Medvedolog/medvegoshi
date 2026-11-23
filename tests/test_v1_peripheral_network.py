"""Radio proof for the real game entry/lazy backend; no sockets or local data."""
import ast
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_main_definitions(*names):
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    definitions = [node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name in names]
    env = {}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), 'main.py', 'exec'), env)
    return env


class RadioPolicyTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('offline_radio_fixture', ROOT / 'rede.py')
        self.rede = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.rede)
        self.rede.time = SimpleNamespace(ticks_ms=lambda: 20, ticks_add=lambda t, n: t + n,
                                         ticks_diff=lambda x, y: x - y)
        self.rede.open = Mock(side_effect=FileNotFoundError)
        self.radio = Mock()
        self.peers = Mock()
        self.network = SimpleNamespace(STA_IF=0, WLAN=Mock(return_value=self.radio))
        self.espnow = SimpleNamespace(ESPNow=Mock(return_value=self.peers))
        modules = patch.dict(sys.modules, {"network": self.network, "espnow": self.espnow})
        modules.start()
        self.addCleanup(modules.stop)

    def test_saved_offline_state_defers_wlan_and_espnow_until_toggle(self):
        r = self.rede
        r.iniciar(sync_clock=False, start_radio=False)
        self.assertEqual(r.situacao(), 0)
        self.assertEqual(r.passo(3000, 1, 'pip'), [])
        self.network.WLAN.assert_not_called()
        self.espnow.ESPNow.assert_not_called()
        r.ficar_offline(False)
        self.network.WLAN.assert_called_once_with(self.network.STA_IF)
        self.radio.active.assert_called_once_with(True)
        self.peers.active.assert_called_once_with(True)
        self.assertFalse(r._sync_clock)
        r.ficar_offline(True)
        r.ficar_offline(False)
        self.assertEqual(self.peers.add_peer.call_count, 2)
        self.assertEqual([call.args for call in self.peers.active.call_args_list],
                         [(True,), (False,), (True,)])

    def test_v1_weather_opt_in_does_not_read_or_write_system_rtc(self):
        r = self.rede
        ntp = SimpleNamespace(settime=Mock(side_effect=AssertionError("unsafe clock write")))
        with patch.dict(sys.modules, {"ntptime": ntp}):
            r.iniciar(sync_clock=False)
            r.wifi = {'ssid': 'local-fixture'}
            r.baixar_clima = lambda: r.clima.update(cod=0, temp=12, vento=0)
            self.assertEqual(r.passo(3020, 12345, 'pip'), [])
            self.radio.isconnected.return_value = True
            self.assertEqual(r.passo(3021, 12345, 'pip')[0], ('clima', 12, 'sol'))
            self.assertEqual(r.clima['epoch'], 12345)
            ntp.settime.assert_not_called()
        self.assertTrue(r.internet_ok)

    def test_wifi_driver_fail_does_not_unwind_game_or_retry_every_frame(self):
        r = self.rede
        r.iniciar(sync_clock=False)
        r.wifi = {'ssid': 'local-fixture'}
        self.assertEqual(r.passo(3020, 12345, 'pip'), [])
        self.radio.isconnected.side_effect = OSError("driver disconnected")
        with patch('builtins.print'):
            self.assertEqual(r.passo(3021, 12345, 'pip')[0], ('sem_wifi',))
            self.assertEqual(r.passo(3022, 12345, 'pip'), [])
        self.radio.connect.assert_called_once()

    def test_startup_and_shutdown_faults_do_not_skip_sta_powerdown(self):
        r = self.rede
        self.radio.config.side_effect = OSError("MAC read failed")
        self.radio.disconnect.side_effect = OSError("disconnect failed")
        with patch('builtins.print'):
            r.iniciar(sync_clock=False)
        self.radio.active.assert_any_call(False)
        self.assertFalse(r._radio_ativo)
        self.assertEqual(r.passo(5000, 123, 'pip'), [])
        self.radio.config.side_effect = None
        self.radio.disconnect.side_effect = None
        r.ficar_offline(False)
        self.assertTrue(r._radio_ativo)
        self.peers.active.side_effect = OSError("ESP-NOW stop failed")
        self.radio.disconnect.side_effect = OSError("disconnect failed")
        self.radio.active.reset_mock()
        with patch('builtins.print'):
            r.ficar_offline(True)
        self.radio.active.assert_called_once_with(False)

    def test_existing_espnow_broadcast_peer_is_not_a_driver_failure(self):
        self.peers.add_peer.side_effect = OSError(123, "ESP_ERR_ESPNOW_EXIST")
        self.rede.iniciar(sync_clock=False)
        self.peers.active.assert_called_once_with(True)
        self.assertIs(self.rede.en, self.peers)

    def test_sta_keeps_working_when_peer_add_fails(self):
        self.peers.add_peer.side_effect = OSError("ESP-NOW add failed")
        with patch('builtins.print'):
            self.rede.iniciar(sync_clock=False)
        self.peers.active.assert_any_call(False)
        self.assertIsNone(self.rede.en)
        self.assertTrue(self.rede._radio_ativo)


class GameBoundaryTest(unittest.TestCase):
    def test_v1_default_never_calls_radio_or_portal(self):
        g = load_main_definitions('abrir_wifi', 'trocar_offline', 'atualizar_rede', 'principal')
        rtc = SimpleNamespace(ler=lambda: (2026, 11, 23, 12, 0, 0))
        msg, radio = Mock(), Mock()
        g.update(runtime_allow_wifi=False, runtime_clock_write=False, rede=radio,
                 sistema=msg, relogio=rtc, limpou_presentes=0,
                 time=SimpleNamespace(ticks_diff=lambda x, y: x - y),
                 hora_real=lambda: 12.0, iniciar_sim=Mock(side_effect=KeyboardInterrupt))
        g['abrir_wifi']()
        g['trocar_offline']()
        g['atualizar_rede'](1)
        with self.assertRaises(KeyboardInterrupt):
            g['principal']()
        self.assertEqual(radio.mock_calls, [])
        self.assertEqual([call.args[0] for call in msg.call_args_list], ['Радио выкл.'] * 2)

    def test_v1_wifi_opt_in_closes_on_interrupt_but_portal_does_not_reset(self):
        g = load_main_definitions('abrir_wifi', 'principal')
        msg, radio, persist = Mock(), Mock(), Mock()
        rtc = SimpleNamespace(ler=lambda: (2026, 11, 23, 12, 0, 0))
        g.update(runtime_allow_wifi=True, runtime_clock_write=False, rede=radio,
                 sistema=msg, relogio=rtc, salvar=persist, cfg={'offline': True},
                 hora_real=lambda: 12.0, iniciar_sim=Mock(side_effect=KeyboardInterrupt))
        g['abrir_wifi']()
        msg.assert_called_once_with('Wi-Fi: через ПК', 3000)
        persist.assert_not_called()
        with self.assertRaises(KeyboardInterrupt):
            g['principal']()
        radio.iniciar.assert_called_once_with(sync_clock=False, start_radio=False)
        radio.ficar_offline.assert_called_once_with(True)

    def test_invalid_v1_rtc_mutes_audio_but_preserves_legacy_ips_rule(self):
        g = load_main_definitions('hora_de_silencio', 'acertar_som')
        rtc = Mock()
        sound = SimpleNamespace(ligado=True)
        g.update(relogio=rtc, som=sound, cfg={'som': True}, SILENCIO_DE=22, SILENCIO_ATE=8)
        for writable, hour, expected in ((False, None, False), (True, None, True),
                                         (False, 7, False), (False, 8, True), (False, 22, False)):
            with self.subTest(writable=writable, hour=hour):
                g['runtime_clock_write'] = writable
                rtc.ler.return_value = None if hour is None else (2026, 11, 23, hour, 0, 0)
                g['acertar_som']()
                self.assertIs(sound.ligado, expected)


if __name__ == '__main__':
    unittest.main()
