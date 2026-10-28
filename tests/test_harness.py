"""Testes sem carro e sem Ollama.  Uso: python -m unittest discover tests"""
import os
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["TE251_DB"] = str(Path(_tmp) / "teste.db")
os.environ["TE251_OLLAMA_URL"] = "http://127.0.0.1:9"   # porta fechada: força 'LLM indisponível'

from te251 import ferramentas as F, guardrails, harness, regras, simulador  # noqa: E402
from te251.store import Store  # noqa: E402


def popular(cenario):
    if getattr(F._local, "store", None):
        F._local.store.db.close()
    F._local.store = None
    for sufixo in ("", "-wal", "-shm"):
        Path(os.environ["TE251_DB"] + sufixo).unlink(missing_ok=True)
    st = Store()
    simulador.rodar(cenario, segundos=2, hz=10, aquecer_s=300, store=st, sleep=False)
    st.db.close()


def chamada(nome, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": nome, "arguments": args}}]}


class TestFerramentas(unittest.TestCase):
    def test_estado_normal_na_estrada(self):
        popular("estrada")
        e = F.get_vehicle_state(["COOLANT_TEMP", "SPEED"])
        self.assertEqual(e["COOLANT_TEMP"]["situacao"], "normal")
        self.assertGreater(e["SPEED"]["valor"], 60)
        self.assertEqual(F.get_dtcs()["quantidade"], 0)

    def test_superaquecimento_gera_dtc(self):
        popular("superaquecimento")
        self.assertEqual([c["codigo"] for c in F.get_dtcs()["codigos"]], ["P0217"])
        self.assertEqual(F.get_history("COOLANT_TEMP", 600)["tendencia"], "subindo")

    def test_autonomia_e_pid_invalido(self):
        popular("tanque_reserva")
        r = F.fuel_range()
        self.assertLess(r["alcance_km"], 20)
        self.assertEqual(r["ponto_de_nao_retorno_km"], round(r["alcance_km"] / 2))
        self.assertIn("erro", F.get_vehicle_state(["XYZ"])["XYZ"])

    def test_busca_na_base(self):
        t = F.search_kb("o que fazer com superaquecimento P0217")["trechos"]
        self.assertTrue(any("P0217" in x["texto"] for x in t))


class TestGuardrails(unittest.TestCase):
    def test_numero_inventado_reprova(self):
        saida = [{"COOLANT_TEMP": {"valor": 92.4, "idade_s": 0.3}}]
        self.assertTrue(guardrails.checar("Temperatura de 92,4 °C, lida há 0,3 s.", saida)[0])
        self.assertTrue(guardrails.checar("Cerca de 92 °C.", saida)[0])
        ok, soltos = guardrails.checar("Temperatura de 98 °C.", saida)
        self.assertFalse(ok)
        self.assertEqual(soltos, [98.0])

    def test_faixa_com_hifen_nao_vira_negativo(self):
        self.assertEqual(guardrails._numeros("faixa normal 80-105 °C"), [80.0, 105.0])
        self.assertEqual(guardrails._numeros("bateria 12,4-14,8 V"), [12.4, 14.8])
        self.assertEqual(guardrails._numeros("externa de -5 °C"), [-5.0])
        saida = [{"COOLANT_TEMP": {"valor": 92.0, "faixa_normal": [80, 105]}}]
        self.assertTrue(guardrails.checar("92 °C, dentro da faixa 80-105 °C.", saida)[0])

    def test_codigo_dtc_nao_conta_como_numero(self):
        self.assertTrue(guardrails.checar("Código P0217 ativo.", [{"quantidade": 1}])[0])


class TestHarness(unittest.TestCase):
    def test_sem_llm_responde_por_regras(self):
        popular("bateria_fraca")
        r = harness.perguntar("Como está a bateria?")
        self.assertIn("regras", r["fonte"])
        self.assertIn("abaixo do normal", r["resposta"])

    def test_llm_falso_usa_ferramenta_e_passa_na_checagem(self):
        popular("estrada")
        temp = F.get_vehicle_state(["COOLANT_TEMP"])["COOLANT_TEMP"]["valor"]
        roteiro = [chamada("get_vehicle_state", pids=["COOLANT_TEMP"]),
                   {"role": "assistant", "content": f"Não. Está em {temp:.0f} °C, dentro do normal."}]
        r = harness.perguntar("O motor está esquentando?", chat=lambda m: roteiro.pop(0))
        self.assertTrue(r["fonte"].startswith("LLM"), r)
        self.assertEqual(r["ferramentas"][0]["ferramenta"], "get_vehicle_state")

    def test_llm_que_inventa_numero_e_substituido(self):
        popular("estrada")
        roteiro = [{"role": "assistant", "content": "A temperatura está em 131 °C."}]
        r = harness.perguntar("Qual a temperatura?", chat=lambda m: roteiro.pop(0))
        self.assertIn("reprovada", r["fonte"])
        self.assertIn("Temperatura do líquido", r["resposta"])

    def test_regras_estado_geral(self):
        popular("turbo_fraco")
        self.assertIn("P0299", regras.responder("Qual o estado geral do carro?"))


if __name__ == "__main__":
    unittest.main()
