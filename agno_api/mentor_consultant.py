from __future__ import annotations

from typing import Any


CONSULTANT_STAGES = {
    "diagnosis",
    "diagnosis_clarification",
    "income_clarification",
    "debt_mapping",
    "reserve_check",
    "action_plan",
    "follow_up",
}

STAGE_FLOW_ORDER = {
    "diagnosis": 0,
    "diagnosis_clarification": 1,
    "income_clarification": 2,
    "debt_mapping": 3,
    "reserve_check": 4,
    "action_plan": 5,
    "follow_up": 6,
}


def normalize_consultant_stage(stage: str | None) -> str:
    value = (stage or "").strip().lower()
    if value in CONSULTANT_STAGES:
        return value
    return "diagnosis"


def normalize_case_summary(summary: Any) -> dict[str, Any]:
    data = summary if isinstance(summary, dict) else {}
    notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    clean_notes = [str(note).strip()[:160] for note in notes if str(note).strip()]
    return {
        "income_extra_type": str(data.get("income_extra_type") or "").strip().lower(),
        "income_extra_origin": str(data.get("income_extra_origin") or "").strip().lower(),
        "has_emergency_reserve": _normalize_binary(data.get("has_emergency_reserve")),
        "debt_outside_cards": _normalize_binary(data.get("debt_outside_cards")),
        "card_payment_behavior": str(data.get("card_payment_behavior") or "").strip().lower(),
        "main_issue_hypothesis": str(data.get("main_issue_hypothesis") or "").strip().lower(),
        "last_user_signal": str(data.get("last_user_signal") or "").strip()[:240],
        "notes": clean_notes[-5:],
    }


def merge_case_summary(
    summary: dict[str, Any] | None,
    user_message: str,
    question_key: str = "",
    expected_answer_type: str = "",
) -> dict[str, Any]:
    merged = normalize_case_summary(summary)
    text = (user_message or "").strip().lower()
    if not text:
        return merged

    merged["last_user_signal"] = (user_message or "").strip()[:240]
    normalized_key = (question_key or "").strip().lower()
    normalized_expected = (expected_answer_type or "").strip().lower()

    income_origin = _extract_income_origin(text)
    if income_origin:
        merged["income_extra_origin"] = income_origin

    income_type = _extract_income_type(text)
    if income_type:
        merged["income_extra_type"] = income_type

    if normalized_key == "has_emergency_reserve" or normalized_expected == "has_reserve":
        reserve_status = _extract_binary_status(text)
        if reserve_status:
            merged["has_emergency_reserve"] = reserve_status

    if normalized_key == "debt_outside_cards" or normalized_expected == "debt_status":
        debt_status = _extract_binary_status(text)
        if debt_status:
            merged["debt_outside_cards"] = debt_status
        if any(
            token in text
            for token in (
                "financiamento",
                "emprestimo",
                "empréstimo",
                "consignado",
                "cheque especial",
                "especial",
                "rotativo",
            )
        ):
            merged["debt_outside_cards"] = "yes"

    card_behavior = _extract_card_payment_behavior(text)
    if card_behavior:
        merged["card_payment_behavior"] = card_behavior

    if normalized_key == "category_other_breakdown":
        _push_note(merged, f"Categoria Outros citada pelo usuario: {(user_message or '').strip()[:100]}")

    merged["main_issue_hypothesis"] = _infer_main_issue_hypothesis(merged)
    return merged


def infer_consultant_stage(
    question_key: str = "",
    expected_answer_type: str = "",
    last_open_question: str = "",
    case_summary: dict[str, Any] | None = None,
) -> str:
    normalized_key = (question_key or "").strip().lower()
    normalized_expected = (expected_answer_type or "").strip().lower()
    question = (last_open_question or "").strip().lower()
    summary = normalize_case_summary(case_summary)

    if normalized_key in {"income_extra_recurrence", "income_extra_origin"}:
        return "income_clarification"
    if normalized_key in {"debt_outside_cards", "card_repayment_behavior"}:
        return "debt_mapping"
    if normalized_key == "has_emergency_reserve":
        return "reserve_check"
    if normalized_key in {"category_other_breakdown", "amount_followup", "open_text_followup", "yes_no_followup"}:
        return "diagnosis_clarification"

    if normalized_expected in {"income_recurrence"}:
        return "income_clarification"
    if normalized_expected in {"debt_status"}:
        return "debt_mapping"
    if normalized_expected in {"has_reserve"}:
        return "reserve_check"
    if normalized_expected in {"number_amount", "open_text", "yes_no"} and question:
        return "diagnosis_clarification"

    if summary.get("main_issue_hypothesis") in {"high_interest_debt", "outside_debt_pressure"}:
        return "action_plan"
    if summary.get("has_emergency_reserve") == "no":
        return "action_plan"
    return "diagnosis"


def transition_consultant_stage(
    current_stage: str = "",
    question_key: str = "",
    expected_answer_type: str = "",
    last_open_question: str = "",
    case_summary: dict[str, Any] | None = None,
) -> str:
    current = normalize_consultant_stage(current_stage)
    inferred = infer_consultant_stage(
        question_key,
        expected_answer_type,
        last_open_question,
        case_summary,
    )
    summary = normalize_case_summary(case_summary)

    if _should_move_to_action_plan(summary, inferred, question_key, expected_answer_type):
        return "action_plan"

    if current == "follow_up":
        return "follow_up"

    if current in {"diagnosis", "diagnosis_clarification"}:
        return inferred

    if current == "income_clarification":
        if STAGE_FLOW_ORDER[inferred] > STAGE_FLOW_ORDER[current]:
            return inferred
        if summary.get("income_extra_type") and summary.get("income_extra_origin"):
            if summary.get("has_emergency_reserve") == "unknown":
                return "reserve_check"
            return "action_plan"
        return "income_clarification"

    if current == "debt_mapping":
        if STAGE_FLOW_ORDER[inferred] > STAGE_FLOW_ORDER[current]:
            return inferred
        if summary.get("debt_outside_cards") != "unknown" or summary.get("card_payment_behavior"):
            if summary.get("has_emergency_reserve") == "unknown":
                return "reserve_check"
            return "action_plan"
        return "debt_mapping"

    if current == "reserve_check":
        if STAGE_FLOW_ORDER[inferred] > STAGE_FLOW_ORDER[current]:
            return inferred
        if summary.get("has_emergency_reserve") != "unknown":
            return "action_plan"
        return "reserve_check"

    if current == "action_plan":
        return "action_plan"

    if STAGE_FLOW_ORDER[inferred] >= STAGE_FLOW_ORDER[current]:
        return inferred
    return current


def build_case_summary_context(case_summary: dict[str, Any] | None) -> str:
    summary = normalize_case_summary(case_summary)
    lines: list[str] = []
    if summary["income_extra_type"]:
        lines.append(f"- Receita extra: {summary['income_extra_type']}")
    if summary["income_extra_origin"]:
        lines.append(f"- Origem da receita extra: {summary['income_extra_origin']}")
    if summary["has_emergency_reserve"] != "unknown":
        lines.append(f"- Reserva de emergencia: {summary['has_emergency_reserve']}")
    if summary["debt_outside_cards"] != "unknown":
        lines.append(f"- Dividas fora dos cartoes: {summary['debt_outside_cards']}")
    if summary["card_payment_behavior"]:
        lines.append(f"- Comportamento com cartao: {summary['card_payment_behavior']}")
    if summary["main_issue_hypothesis"]:
        lines.append(f"- Hipotese principal: {summary['main_issue_hypothesis']}")
    if summary["last_user_signal"]:
        lines.append(f"- Ultimo sinal do usuario: {summary['last_user_signal']}")
    for note in summary["notes"][-2:]:
        lines.append(f"- Nota: {note}")
    return "\n".join(lines)


def build_consultant_plan(case_summary: dict[str, Any] | None, stage: str = "") -> dict[str, str]:
    summary = normalize_case_summary(case_summary)
    normalized_stage = normalize_consultant_stage(stage)
    hypothesis = summary.get("main_issue_hypothesis")

    problem = "falta clareza sobre para onde o dinheiro esta vazando"
    why = "sem diagnostico claro, a pessoa continua ajustando detalhes e ignora o vazamento principal"
    first_move = "identificar a categoria ou comportamento que mais pesa no mes antes de falar de investimento"
    next_priority = "fechar uma pergunta objetiva que destrave a proxima decisao"

    if hypothesis == "high_interest_debt":
        problem = "divida cara ou pagamento ruim do cartao"
        why = "juros altos destroem qualquer tentativa de organizar o mes"
        first_move = "parar rotativo ou minimo e reorganizar pagamento da fatura antes de qualquer outro plano"
        next_priority = "mapear se ha outras dividas fora dos cartoes"
    elif hypothesis == "outside_debt_pressure":
        problem = "dividas fora do cartao comprimindo o caixa"
        why = "parcelas e financiamentos podem estar escondendo o problema principal do mes"
        first_move = "mapear quais dividas existem, custo e peso mensal antes de cortar categorias menores"
        next_priority = "entender reserva e folego de caixa"
    elif hypothesis == "no_emergency_buffer":
        problem = "sem reserva de emergencia"
        why = "qualquer imprevisto empurra a pessoa de volta para cartao, emprestimo ou descontrole"
        first_move = "criar uma reserva minima e parar de depender do improviso"
        next_priority = "definir de onde sai o primeiro valor para essa reserva"
    elif hypothesis == "income_volatility":
        problem = "receita extra instavel confundindo a leitura do mes"
        why = "se renda pontual vira base do padrao de vida, o orcamento quebra facil"
        first_move = "separar o que e renda recorrente do que foi so alivio pontual"
        next_priority = "organizar gastos fixos como se a renda extra nao existisse"

    if normalized_stage == "income_clarification":
        next_priority = "confirmar se a renda extra e recorrente ou pontual e de onde ela veio"
    elif normalized_stage == "debt_mapping":
        next_priority = "mapear dividas e comportamento do cartao para priorizar o risco certo"
    elif normalized_stage == "reserve_check":
        next_priority = "entender se existe reserva para saber se o proximo passo e protecao ou ataque a divida"
    elif normalized_stage == "action_plan":
        next_priority = "traduzir o diagnostico em uma primeira acao simples e executavel nesta semana"

    return {
        "primary_problem": problem,
        "why_it_matters": why,
        "first_move": first_move,
        "next_priority": next_priority,
    }


def build_consultant_plan_context(case_summary: dict[str, Any] | None, stage: str = "") -> str:
    plan = build_consultant_plan(case_summary, stage)
    return "\n".join(
        [
            f"- Problema principal: {plan['primary_problem']}",
            f"- Por que importa: {plan['why_it_matters']}",
            f"- Primeira acao recomendada: {plan['first_move']}",
            f"- Proxima prioridade: {plan['next_priority']}",
        ]
    )


def infer_pri_opening_frame(
    user_message: str,
    month_snapshot: dict[str, Any] | None = None,
    case_summary: dict[str, Any] | None = None,
) -> str:
    text = (user_message or "").strip().lower()
    snapshot = month_snapshot if isinstance(month_snapshot, dict) else {}
    summary = normalize_case_summary(case_summary)
    card_total = int(snapshot.get("card_total_cents") or 0)

    monthly_signals = (
        "analise do meu mes",
        "análise do meu mês",
        "analise do meu mês",
        "analisa meu mes",
        "analisa meu mês",
        "raio x do meu mes",
        "raio-x do meu mes",
        "onde esta indo o dinheiro",
        "onde ta indo o dinheiro",
        "onde tá indo o dinheiro",
        "onde esta indo meu dinheiro",
        "onde ta indo meu dinheiro",
        "onde tá indo meu dinheiro",
    )
    if any(signal in text for signal in ("analise do dia", "análise do dia", "analise de hoje", "análise de hoje", "meu dia")):
        return "daily_analysis"
    if "analise de ontem" in text or "análise de ontem" in text or "meu ontem" in text:
        return "yesterday_analysis"
    if "analise da semana passada" in text or "análise da semana passada" in text or "semana passada" in text:
        return "last_week_analysis"
    if any(signal in text for signal in ("ultimos 7 dias", "últimos 7 dias", "ultima semana", "última semana")):
        return "last_7_days_analysis"
    if any(signal in text for signal in ("analise da semana", "análise da semana", "minha semana", "essa semana", "esta semana")):
        return "weekly_analysis"
    if any(signal in text for signal in monthly_signals):
        return "monthly_analysis"

    if any(token in text for token in ("cheque especial", "especial", "rotativo", "minimo", "mínimo")):
        return "high_interest_debt"

    if any(token in text for token in ("cartao", "cartão", "fatura")) and any(
        token in text for token in ("devendo", "divida", "dívida", "pagar", "parcel")
    ):
        return "card_debt"

    if any(token in text for token in ("reserva", "emergencia", "emergência")):
        return "reserve"

    if any(token in text for token in ("invest", "aplicar", "cdb", "tesouro", "guardar")):
        if summary.get("main_issue_hypothesis") in {"high_interest_debt", "outside_debt_pressure"} or card_total >= 150000:
            return "invest_vs_debt"
        return "investing"

    if any(token in text for token in ("divida", "dívida", "emprestimo", "empréstimo", "devendo")):
        return "debt_mapping"

    return ""


def build_structured_pri_opening(
    user_message: str,
    month_snapshot: dict[str, Any] | None,
    case_summary: dict[str, Any] | None = None,
) -> dict[str, str]:
    snapshot = month_snapshot if isinstance(month_snapshot, dict) else {}
    summary = normalize_case_summary(case_summary)
    categories = snapshot.get("top_categories") if isinstance(snapshot.get("top_categories"), list) else []
    frame = infer_pri_opening_frame(user_message, snapshot, summary)

    reference_income = int(snapshot.get("actual_income_cents") or 0) or int(snapshot.get("declared_income_cents") or 0)
    expense_total = int(snapshot.get("expense_total_cents") or 0)
    card_total = int(snapshot.get("card_total_cents") or 0)
    explicit_amount = _extract_brl_amount_cents(user_message)

    def _find_category(*names: str) -> dict[str, Any]:
        wanted = {name.strip().lower() for name in names if name}
        for item in categories:
            category_name = str(item.get("name") or "").strip().lower()
            if category_name in wanted:
                return item
        return {}

    others = _find_category("outros")
    food = _find_category("alimentacao", "alimentação")
    housing = _find_category("moradia")

    others_total = int(others.get("total_cents") or 0)
    food_total = int(food.get("total_cents") or 0)
    food_count = int(food.get("count") or 0)
    housing_total = int(housing.get("total_cents") or 0)
    period_label = str(snapshot.get("period_label") or "esse periodo").strip() or "esse periodo"
    has_complete_month_history = bool(snapshot.get("has_complete_month_history"))
    no_history_note = ""
    if not has_complete_month_history:
        no_history_note = (
            "E um detalhe importante: eu ainda nao tenho pelo menos 1 mes fechado teu "
            "pra comparar media mensal com seguranca.\n\n"
        )

    issue = "general_leak"
    question = "Me responde uma coisa: hoje voce sente mais aperto com cartao, com gasto do dia a dia ou com conta fixa?"
    question_key = "open_text_followup"
    expected_answer_type = "open_text"
    main_hypothesis = summary.get("main_issue_hypothesis") or "cashflow_pressure"

    if frame in {"daily_analysis", "yesterday_analysis", "weekly_analysis", "last_week_analysis", "last_7_days_analysis"}:
        if others_total >= max(8000, int(expense_total * 0.18) if expense_total else 8000):
            issue = "temporal_others_leak"
            question = f"Me diz: esse *Outros* de {period_label} voce ja sabe o que foi ou saiu tudo no automatico?"
            question_key = "category_other_breakdown"
            expected_answer_type = "open_text"
            main_hypothesis = "cashflow_pressure"
        elif food_count >= 3 and food_total >= 3000:
            issue = "temporal_food_frequency"
            question = f"Nesse recorte de {period_label}, isso foi mais mercado, delivery ou comer fora?"
            question_key = "open_text_followup"
            expected_answer_type = "open_text"
            main_hypothesis = "cashflow_pressure"
        elif housing_total > 0:
            issue = "temporal_housing_weight"
            question = f"Em {period_label}, essa moradia foi so conta fixa normal ou entrou alguma coisa fora da curva?"
            question_key = "open_text_followup"
            expected_answer_type = "open_text"
            main_hypothesis = "cashflow_pressure"
        else:
            issue = "temporal_general_leak"
            question = f"Em {period_label}, o que mais te deu sensacao de descontrole: comida, impulso ou conta fixa?"
            question_key = "open_text_followup"
            expected_answer_type = "open_text"
            main_hypothesis = "cashflow_pressure"
    elif frame == "high_interest_debt":
        issue = "high_interest_debt"
        debt_amount = explicit_amount or card_total
        question = "Me responde com sinceridade: voce consegue levantar parte disso ainda este mes ou vai precisar montar uma saida parcelada?"
        question_key = "open_text_followup"
        expected_answer_type = "open_text"
        main_hypothesis = "high_interest_debt"
    elif frame == "card_debt":
        issue = "card_pressure"
        question = "Antes de pensar no resto, me diz: voce ta pagando essa fatura toda ou ta ficando no minimo/parcelando?"
        question_key = "card_repayment_behavior"
        expected_answer_type = "debt_status"
        main_hypothesis = "high_interest_debt"
    elif frame == "reserve":
        issue = "reserve_gap"
        question = "Hoje voce consegue separar quanto por mes sem se enrolar: *R$100*, *R$300* ou mais?"
        question_key = "amount_followup"
        expected_answer_type = "number_amount"
        main_hypothesis = "no_emergency_buffer"
    elif frame == "invest_vs_debt":
        issue = "invest_vs_debt"
        question = "Me diz uma coisa: hoje voce tem alguma divida cara rodando ou ta tudo pago em dia?"
        question_key = "debt_outside_cards"
        expected_answer_type = "debt_status"
        main_hypothesis = "high_interest_debt"
    elif frame == "investing":
        issue = "investing_start"
        question = "Antes de eu te dizer onde investir, me responde: hoje voce ja tem reserva montada ou ainda nao?"
        question_key = "has_emergency_reserve"
        expected_answer_type = "has_reserve"
        main_hypothesis = summary.get("main_issue_hypothesis") or ""
    elif frame == "debt_mapping":
        issue = "debt_mapping"
        question = "Me fala sem enfeitar: essa divida hoje ta mais em cartao, emprestimo ou cheque especial?"
        question_key = "debt_outside_cards"
        expected_answer_type = "debt_status"
        main_hypothesis = "outside_debt_pressure"
    elif others_total >= max(250000, int(expense_total * 0.18) if expense_total else 250000):
        issue = "others_leak"
        question = f"Me diz uma coisa: esses *{_fmt_cents_brl(others_total)}* em *Outros* voce ja sabe o que sao ou ta tudo misturado?"
        question_key = "category_other_breakdown"
        expected_answer_type = "open_text"
        main_hypothesis = "cashflow_pressure"
    elif card_total >= max(150000, int(reference_income * 0.35) if reference_income else 150000):
        issue = "card_pressure"
        question = "Antes de falar do resto, me diz: voce ta pagando essa fatura toda ou ta ficando no minimo/parcelando?"
        question_key = "card_repayment_behavior"
        expected_answer_type = "debt_status"
        main_hypothesis = "high_interest_debt"
    elif food_count >= 20 and food_total >= 150000:
        issue = "food_frequency"
        question = "Me diz: esse gasto foi mais mercado, delivery ou comer fora?"
        question_key = "open_text_followup"
        expected_answer_type = "open_text"
        main_hypothesis = "cashflow_pressure"
    elif housing_total >= max(300000, int(reference_income * 0.35) if reference_income else 300000):
        issue = "housing_weight"
        question = "Me responde uma coisa: nessa moradia tem so aluguel/financiamento ou tem mais coisa pesada junto?"
        question_key = "open_text_followup"
        expected_answer_type = "open_text"
        main_hypothesis = "cashflow_pressure"

    if issue == "temporal_others_leak":
        content = (
            f"Pri aqui. Em {period_label}, teu dinheiro nao explodiu num lugar so. Ele vazou.\n\n"
            "E o ponto mais suspeito pra mim e *Outros*. Quando essa categoria pesa num recorte curto, quase sempre teve gasto saindo no automatico.\n\n"
            f"{no_history_note}"
            "Se eu estivesse arrumando isso com voce, eu abriria esse bloco primeiro. Porque e ali que normalmente fica o ralo.\n\n"
            f"{question}"
        )
    elif issue == "temporal_food_frequency":
        content = (
            f"Pri aqui. Em {period_label}, o problema nao parece ser um gasto gigante. E repeticao.\n\n"
            "Quando alimentacao aparece toda hora, o dinheiro vai embora pingando e voce so sente o tranco depois.\n\n"
            f"{no_history_note}"
            "Se eu estivesse organizando isso com voce, eu comecaria por aqui. Porque esse tipo de vazamento e rapido de sentir no bolso.\n\n"
            f"{question}"
        )
    elif issue == "temporal_housing_weight":
        content = (
            f"Pri aqui. Em {period_label}, o peso veio de conta grande, nao de besteira do dia a dia.\n\n"
            "Quando moradia domina o recorte, nao adianta procurar culpado em cafezinho. A pergunta certa e: o que entrou aqui alem do normal?\n\n"
            f"{no_history_note}"
            "Se eu estivesse olhando isso com voce, eu separaria o fixo do que foi fora da curva.\n\n"
            f"{question}"
        )
    elif issue == "temporal_general_leak":
        content = (
            f"Pri aqui. Em {period_label}, teu dinheiro nao sumiu numa compra so. Ele foi escapando aos poucos.\n\n"
            "Quando isso acontece, normalmente o problema e rotina sem controle, nao uma decisao gigante.\n\n"
            f"{no_history_note}"
            "Se eu estivesse organizando isso com voce, eu atacaria primeiro o bloco mais repetido. Porque e ali que o dinheiro escapa sem pedir permissao.\n\n"
            f"{question}"
        )
    elif issue == "high_interest_debt":
        debt_amount = explicit_amount or card_total
        debt_label = _fmt_cents_brl(debt_amount) if debt_amount else "essa divida"
        content = (
            f"Pri aqui. O problema aqui nao e so *{debt_label}*. E o custo desse dinheiro mordendo teu mes.\n\n"
            "Cheque especial e rotativo sao o tipo de divida que cresce quieta. Quando voce percebe, ela ja comeu um pedaco do teu folego.\n\n"
            "Se eu estivesse organizando isso com voce, minha prioridade 1 seria parar esse sangramento antes de falar de qualquer outro ajuste.\n\n"
            f"{question}"
        )
    elif issue == "card_pressure":
        content = (
            "Pri aqui. Vou te falar sem rodeio: o que mais me preocupa no teu mes nao e cafezinho nem delivery. "
            "E cartao puxando teu caixa.\n\n"
            f"Hoje voce tem *{_fmt_cents_brl(card_total)}* em faturas abertas. Se isso escorrega pra minimo ou rotativo, "
            "vira dinheiro queimando sem trazer nada em troca.\n\n"
            f"{no_history_note}"
            "Se eu estivesse organizando isso com voce, eu travaria esse risco antes de mexer no resto.\n\n"
            f"{question}"
        )
    elif issue == "reserve_gap":
        content = (
            "Pri aqui. Antes de pensar em fazer dinheiro crescer, tem um buraco mais urgente pra fechar: protecao.\n\n"
            "Sem reserva, qualquer imprevisto te empurra de volta pra cartao, emprestimo ou cheque especial. A vida vira improviso.\n\n"
            "Se eu estivesse organizando isso com voce, eu montaria uma reserva pequena primeiro. Sem isso, qualquer plano fica bambu.\n\n"
            f"{question}"
        )
    elif issue == "invest_vs_debt":
        content = (
            "Pri aqui. Vou ser direta: se tiver divida cara correndo, investir agora vira maquiagem financeira.\n\n"
            "O dinheiro rende de um lado e sangra muito mais do outro. Antes de falar de CDB ou Tesouro, tem fogo pra apagar.\n\n"
            "Se eu estivesse te assessorando, eu confirmaria isso primeiro. Prioridade boa e a que para de te fazer perder dinheiro.\n\n"
            f"{question}"
        )
    elif issue == "investing_start":
        content = (
            "Pri aqui. Antes de eu te dizer onde investir, eu preciso olhar o chao onde voce vai pisar.\n\n"
            "Quem investe sem reserva acaba sacando na primeira pancada. A estrategia quebra na primeira curva.\n\n"
            "Se eu estivesse montando isso com voce, eu validaria essa base antes de falar de produto.\n\n"
            f"{question}"
        )
    elif issue == "debt_mapping":
        content = (
            "Pri aqui. O problema aqui nao e so o valor da divida. E onde ela mora.\n\n"
            "Cartao, cheque especial e emprestimo pesam de jeitos bem diferentes no teu caixa. E isso muda completamente a ordem do plano.\n\n"
            "Se eu estivesse organizando isso com voce, eu mapearia a fonte da pressao antes de falar de qualquer saida.\n\n"
            f"{question}"
        )
    elif issue == "others_leak":
        content = (
            "Pri aqui. Vou te falar sem rodeio: teu problema esse mes nao e falta de renda. E vazamento.\n\n"
            f"O maior alerta pra mim e *Outros* com *{_fmt_cents_brl(others_total)}*. Quando muito dinheiro cai em categoria generica, quase sempre tem gasto escondido ali.\n\n"
            f"{no_history_note}"
            "Se eu estivesse arrumando isso com voce, eu comecaria abrindo esse *Outros* hoje. Porque e ali que o dinheiro some sem fazer barulho.\n\n"
            f"{question}"
        )
    elif issue == "food_frequency":
        content = (
            "Pri aqui. O problema aqui nao e mercado. E frequencia.\n\n"
            f"Alimentacao ja bateu *{_fmt_cents_brl(food_total)}* em *{food_count} compras*. Quando a frequencia sobe assim, o dinheiro vai embora sem fazer barulho.\n\n"
            f"{no_history_note}"
            "Se eu estivesse organizando isso com voce, eu abriria os ultimos 15 dias dessa categoria antes de falar de qualquer outro ajuste.\n\n"
            f"{question}"
        )
    elif issue == "housing_weight":
        content = (
            "Pri aqui. Vou direto na ferida: teu mes ta pesado demais nas contas que voce nao consegue empurrar pra depois.\n\n"
            f"Moradia sozinha ta em *{_fmt_cents_brl(housing_total)}*. Quando esse bloco pesa assim, o resto do orcamento fica sem ar.\n\n"
            f"{no_history_note}"
            "Se eu estivesse te assessorando, eu separaria o que e fixo de verdade e o que entrou junto nessa conta.\n\n"
            f"{question}"
        )
    else:
        problem_text = "teu dinheiro entrou em modo reativo" if reference_income and expense_total > reference_income else "tem vazamento no teu mes"
        content = (
            f"Pri aqui. Vou te falar sem rodeio: o problema aqui nao e detalhe pequeno. E que {problem_text}.\n\n"
            "Quando o mes fica sem um centro claro de controle, qualquer categoria comeca a puxar mais do que deveria.\n\n"
            f"{no_history_note}"
            "Se eu estivesse organizando isso com voce, eu escolheria primeiro onde atacar de verdade em vez de sair cortando tudo no susto.\n\n"
            f"{question}"
        )

    return {
        "frame": frame,
        "content": content,
        "question": question,
        "open_question_key": question_key,
        "expected_answer_type": expected_answer_type,
        "main_issue_hypothesis": main_hypothesis,
    }


def build_structured_pri_followup(
    user_message: str,
    question_key: str = "",
    expected_answer_type: str = "",
    case_summary: dict[str, Any] | None = None,
    stage: str = "",
    last_open_question: str = "",
) -> dict[str, Any]:
    text = (user_message or "").strip()
    lowered = text.lower()
    normalized_key = (question_key or "").strip().lower()
    normalized_expected = (expected_answer_type or "").strip().lower()
    normalized_last_question = (last_open_question or "").strip().lower()
    merged_summary = merge_case_summary(case_summary, text, normalized_key, normalized_expected)
    amount_cents = _extract_brl_amount_cents(text)

    if any(token in lowered for token in ("cheque especial", "especial", "rotativo", "emprestimo", "empréstimo", "financiamento")) and any(
        token in lowered
        for token in ("nao tenho reserva", "não tenho reserva", "sem reserva", "nao tenho nenhuma reserva", "não tenho nenhuma reserva")
    ):
        amount_label = _fmt_cents_brl(amount_cents) if amount_cents else "essa divida"
        question = "Me diz uma coisa: voce consegue levantar uma parte disso ainda este mes ou primeiro precisa abrir espaco no teu orcamento?"
        merged_summary["debt_outside_cards"] = "yes"
        merged_summary["has_emergency_reserve"] = "no"
        merged_summary["main_issue_hypothesis"] = "high_interest_debt"
        content = (
            f"Pri aqui. Aí acendeu alerta vermelho de verdade: *{amount_label}* no cheque especial e *zero reserva*.\n\n"
            "Isso e o tipo de combinacao que machuca rapido, porque o juros corre e voce fica sem colchao pra absorver qualquer imprevisto.\n\n"
            "Se eu estivesse organizando isso com voce, a ordem seria bem clara: primeiro parar esse sangramento, depois criar uma reserva minima pra nao voltar pro especial.\n\n"
            f"{question}"
        )
        return {
            "content": content,
            "question": question,
            "open_question_key": "amount_followup",
            "expected_answer_type": "open_text",
            "consultant_stage": "action_plan",
            "case_summary": merged_summary,
        }

    def _is_affirmative() -> bool:
        return any(token in lowered for token in ("sim", "quero", "bora", "vamos", "pode", "claro", "quero sim"))

    def _is_negative() -> bool:
        return any(token in lowered for token in ("nao", "não", "deixa", "agora nao", "agora não", "depois"))

    debt_followup_requested = (
        normalized_key == "debt_outside_cards"
        or normalized_expected == "debt_status"
        or (
            normalize_consultant_stage(stage) == "debt_mapping"
            and any(token in lowered for token in ("cheque especial", "especial", "rotativo", "emprestimo", "empréstimo", "financiamento"))
        )
    )

    if normalized_key in {"income_extra_recurrence", "income_extra_origin"}:
        income_origin = merged_summary.get("income_extra_origin", "")
        income_type = merged_summary.get("income_extra_type", "")
        if income_origin and not income_type:
            question = "Isso foi pontual ou entra com alguma frequencia?"
            content = (
                f"Boa. Entao essa entrada extra veio de *{income_origin}*.\n\n"
                "Agora eu preciso separar uma coisa: isso foi alivio pontual ou da pra contar com esse dinheiro de novo? "
                "Porque isso muda totalmente o plano.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "income_extra_recurrence",
                "expected_answer_type": "income_recurrence",
                "consultant_stage": "income_clarification",
                "case_summary": merged_summary,
            }
        if income_type and merged_summary.get("has_emergency_reserve") == "unknown":
            question = "Hoje voce tem alguma reserva ou ainda ta no zero de protecao?"
            tone = "isso nao pode virar base do teu padrao de vida" if income_type == "pontual" else "isso ajuda, mas eu nao quero te ver relaxando no controle"
            content = (
                f"Perfeito. Entao essa renda extra foi *{income_type}*.\n\n"
                f"O ponto aqui e simples: {tone}.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "has_emergency_reserve",
                "expected_answer_type": "has_reserve",
                "consultant_stage": "reserve_check",
                "case_summary": merged_summary,
            }

    if debt_followup_requested:
        if any(token in lowered for token in ("cheque especial", "especial", "rotativo")) and any(
            token in lowered for token in ("nao tenho reserva", "não tenho reserva", "sem reserva", "nao tenho nenhuma reserva", "não tenho nenhuma reserva")
        ):
            amount_label = _fmt_cents_brl(amount_cents) if amount_cents else "essa divida"
            question = "Me diz uma coisa: voce consegue levantar uma parte disso ainda este mes ou primeiro precisa abrir espaco no teu orcamento?"
            merged_summary["main_issue_hypothesis"] = "high_interest_debt"
            merged_summary["has_emergency_reserve"] = "no"
            content = (
                f"Pri aqui. Aí acendeu alerta vermelho de verdade: *{amount_label}* no cheque especial e *zero reserva*.\n\n"
                "Isso e o tipo de combinacao que machuca rapido, porque o juros corre e voce fica sem colchao pra absorver qualquer imprevisto.\n\n"
                "Se eu estivesse organizando isso com voce, a ordem seria bem clara: primeiro parar esse sangramento, depois criar uma reserva minima pra nao voltar pro especial.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "amount_followup",
                "expected_answer_type": "open_text",
                "consultant_stage": "action_plan",
                "case_summary": merged_summary,
            }
        if any(token in lowered for token in ("cheque especial", "especial", "rotativo")):
            amount_label = _fmt_cents_brl(amount_cents) if amount_cents else "isso"
            question = f"Voce consegue tirar {amount_label} disso ainda este mes ou vai precisar montar uma saida parcelada?"
            merged_summary["main_issue_hypothesis"] = "high_interest_debt"
            content = (
                "Aí acendeu alerta vermelho.\n\n"
                f"Cheque especial e uma das piores dividas que tem. Esses *{amount_label}* parecem pequenos, mas esse dinheiro caro morde teu mes sem fazer barulho.\n\n"
                "Se eu estivesse arrumando isso com voce, minha prioridade 1 seria te tirar disso antes de qualquer ajuste mais bonito.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "amount_followup",
                "expected_answer_type": "open_text",
                "consultant_stage": "action_plan",
                "case_summary": merged_summary,
            }
        if merged_summary.get("debt_outside_cards") == "no":
            question = "Fechado. E no cartao: voce paga a fatura toda ou ta ficando no minimo/parcelando?"
            content = (
                "Boa. Entao a pressao nao ta vindo de emprestimo por fora.\n\n"
                "Agora eu quero olhar o ponto mais perigoso seguinte: comportamento da fatura. Porque e ali que muita gente escorrega sem perceber.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "card_repayment_behavior",
                "expected_answer_type": "debt_status",
                "consultant_stage": "debt_mapping",
                "case_summary": merged_summary,
            }

    if normalized_key == "card_repayment_behavior":
        behavior = merged_summary.get("card_payment_behavior", "")
        if behavior in {"rotativo", "minimo", "parcial"}:
            question = "Alem do cartao, voce tambem ta usando cheque especial ou tem emprestimo correndo?"
            merged_summary["main_issue_hypothesis"] = "high_interest_debt"
            content = (
                f"Entendi. Entao teu cartao ja ta em modo *{behavior}*.\n\n"
                "Isso e o tipo de coisa que destrói o mes sem fazer alarde. Antes de pensar em qualquer outra meta, eu pisaria no freio aqui.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "debt_outside_cards",
                "expected_answer_type": "debt_status",
                "consultant_stage": "debt_mapping",
                "case_summary": merged_summary,
            }
        if behavior == "total" and merged_summary.get("has_emergency_reserve") == "unknown":
            question = "Hoje voce tem alguma reserva ou ainda ta sem colchao de seguranca?"
            content = (
                "Boa. Pagar a fatura inteira ja tira um risco grande da mesa.\n\n"
                "Agora eu quero entender teu folego. Porque organizacao sem reserva vira equilibrio em cima de corda bamba.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "has_emergency_reserve",
                "expected_answer_type": "has_reserve",
                "consultant_stage": "reserve_check",
                "case_summary": merged_summary,
            }

    if normalized_key == "has_emergency_reserve":
        reserve_status = merged_summary.get("has_emergency_reserve", "unknown")
        if reserve_status == "no":
            question = "Hoje, sem se enrolar, voce consegue separar quanto por mes: R$100, R$300 ou mais?"
            merged_summary["main_issue_hypothesis"] = "no_emergency_buffer"
            content = (
                "Aí está um ponto central.\n\n"
                "Sem reserva, qualquer tropeço te empurra pra cheque especial, cartao ou improviso. A vida financeira fica sempre jogando na defesa.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "amount_followup",
                "expected_answer_type": "number_amount",
                "consultant_stage": "action_plan",
                "case_summary": merged_summary,
            }
        if reserve_status == "yes":
            question = "Boa. Essa reserva hoje cobre mais ou menos quantos meses teus?"
            content = (
                "Boa. Ter reserva ja muda o jogo.\n\n"
                "Agora eu quero medir o tamanho desse folego. Porque ter alguma reserva e diferente de ter uma reserva que realmente te protege.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "open_text_followup",
                "expected_answer_type": "open_text",
                "consultant_stage": "reserve_check",
                "case_summary": merged_summary,
            }

    if normalized_key == "amount_followup":
        if _is_negative() or any(token in lowered for token in ("nao separo", "não separo", "nao consigo", "não consigo", "sem folga", "apertado")):
            question = "Entao me diz sem rodeio: hoje o que daria pra cortar primeiro sem te machucar tanto - delivery, impulso ou alguma coisa em Outros?"
            merged_summary["main_issue_hypothesis"] = "no_emergency_buffer"
            content = (
                "Fechado. Entao o problema agora nao e falta de vontade. E falta de folga.\n\n"
                "Se voce nao consegue separar nada hoje, eu nao comecaria falando de reserva bonita. Eu comecaria abrindo espaco no teu mes.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "open_text_followup",
                "expected_answer_type": "open_text",
                "consultant_stage": "action_plan",
                "case_summary": merged_summary,
            }
        if amount_cents > 0:
            amount_label = _fmt_cents_brl(amount_cents)
            question = f"Boa. Esse {amount_label} sairia de onde na pratica: corte de gasto, renda extra ou sobra natural do mes?"
            merged_summary["main_issue_hypothesis"] = merged_summary.get("main_issue_hypothesis") or "no_emergency_buffer"
            content = (
                f"Boa. Entao da pra comecar com *{amount_label}* por mes.\n\n"
                "Nao e sobre velocidade agora. E sobre parar de ficar exposto todo mes e criar o primeiro colchao.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "open_text_followup",
                "expected_answer_type": "open_text",
                "consultant_stage": "action_plan",
                "case_summary": merged_summary,
            }

    if normalized_key == "plan_help_offer":
        if _is_negative():
            content = (
                "Fechado. Sem pressa.\n\n"
                "Quando quiser, eu monto isso com voce sem enrolacao. So me chama de novo."
            )
            return {
                "content": content,
                "question": "",
                "open_question_key": "",
                "expected_answer_type": "",
                "consultant_stage": "follow_up",
                "case_summary": merged_summary,
            }
        if _is_affirmative():
            plan = build_consultant_plan(merged_summary, stage or "action_plan")
            question = "Pra montar isso direito, me diz: hoje o que mais te derruba e delivery, impulso ou conta fixa?"
            content = (
                "Fechou. Entao vamos montar isso sem inventar moda.\n\n"
                f"O foco agora e: *{plan['first_move']}*.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "open_text_followup",
                "expected_answer_type": "open_text",
                "consultant_stage": "action_plan",
                "case_summary": merged_summary,
            }

    if normalized_key == "open_text_followup":
        asking_for_invoice_breakdown = (
            any(token in normalized_last_question for token in ("fatura", "maiores gastos", "listar"))
            or any(token in " ".join(merged_summary.get("notes", [])) for token in ("fatura", "cartao", "caixa"))
        )
        asking_for_card_type = any(
            token in normalized_last_question
            for token in ("cartao de credito", "cartão de crédito", "emprestimo", "empréstimo", "financiamento")
        )
        if asking_for_card_type and any(
            token in lowered for token in ("cartao de credito", "cartão de crédito", "credito", "crédito")
        ):
            question = (
                "Boa. Agora me diz o que mais pesa nessa fatura: mercado do dia a dia, "
                "parcela grande, aluguel ou outra coisa?"
            )
            content = (
                "Perfeito. Entao a raiz nao e emprestimo nem financiamento. E *cartao de credito* mesmo.\n\n"
                "Isso ajuda porque agora eu sei que esse bolo em Outros esta misturando fatura com gasto do mes. "
                "O proximo passo e separar o que nessa fatura e rotina e o que e peso fora do normal.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "open_text_followup",
                "expected_answer_type": "open_text",
                "consultant_stage": "diagnosis_clarification",
                "case_summary": merged_summary,
            }
        if _is_affirmative() and asking_for_invoice_breakdown:
            question = (
                "Boa. Entao me fala os 3 maiores gastos que voce lembra dessa fatura: "
                "mercado, aluguel, app, transporte, qualquer coisa nessa linha."
            )
            content = (
                "Perfeito. Entao a gente nao precisa voltar pro resumo do mes agora. "
                "A gente precisa abrir essa fatura por partes.\n\n"
                "Se voce me trouxer os maiores blocos, eu separo com voce o que e cartao, "
                "o que e gasto fixo e o que e vazamento de verdade.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "open_text_followup",
                "expected_answer_type": "open_text",
                "consultant_stage": "diagnosis_clarification",
                "case_summary": merged_summary,
            }
        if _is_negative() and asking_for_invoice_breakdown:
            question = "Sem problema. Qual e o primeiro gasto dessa fatura que voce lembra agora, mesmo que seja so um?"
            content = (
                "Fechado. Nao precisa me trazer tudo de uma vez.\n\n"
                "Se voce lembrar de um gasto so, a gente ja comeca a desmontar esse bolo sem chute.\n\n"
                f"{question}"
            )
            return {
                "content": content,
                "question": question,
                "open_question_key": "open_text_followup",
                "expected_answer_type": "open_text",
                "consultant_stage": "diagnosis_clarification",
                "case_summary": merged_summary,
            }

    return {}


def _normalize_binary(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"yes", "no", "unknown"}:
        return text
    return "unknown"


def _fmt_cents_brl(value_cents: int | float | None) -> str:
    value = float(value_cents or 0) / 100.0
    formatted = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if formatted.endswith(",00"):
        formatted = formatted[:-3]
    return f"R${formatted}"


def _extract_brl_amount_cents(text: str) -> int:
    import re

    raw = str(text or "").lower()
    patterns = [
        r"r\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)",
        r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?|\d+(?:,\d{1,2})?)\s*(mil)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if not match:
            continue
        number = (match.group(1) or "").strip()
        multiplier = 1000 if len(match.groups()) > 1 and (match.group(2) or "").strip() else 1
        normalized = number.replace(".", "").replace(",", ".")
        try:
            value = float(normalized) * multiplier
            return int(round(value * 100))
        except Exception:
            continue
    return 0


def _extract_binary_status(text: str) -> str:
    lowered = (text or "").strip().lower()
    if not lowered:
        return ""
    if any(token in lowered for token in ("nao", "não", "sem ", "nunca", "zero")):
        return "no"
    if any(token in lowered for token in ("sim", "tenho", "guardo", "possuo", "tem ", "tô com", "to com")):
        return "yes"
    return ""


def _extract_income_origin(text: str) -> str:
    mapping = {
        "plantao": "plantao",
        "plantão": "plantao",
        "freela": "freela",
        "freelance": "freelance",
        "bonus": "bonus",
        "bônus": "bonus",
        "comissao": "comissao",
        "comissão": "comissao",
        "hora extra": "hora extra",
        "venda": "venda",
        "pix": "pix",
    }
    for token, label in mapping.items():
        if token in text:
            return label
    return ""


def _extract_income_type(text: str) -> str:
    recurring_tokens = ("recorrente", "todo mes", "todo mês", "fixa", "fixo", "sempre")
    one_off_tokens = ("pontual", "so esse mes", "só esse mês", "esse mes", "esse mês", "foi so", "foi só")
    if any(token in text for token in recurring_tokens):
        return "recorrente"
    if any(token in text for token in one_off_tokens):
        return "pontual"
    return ""


def _extract_card_payment_behavior(text: str) -> str:
    if any(token in text for token in ("rotativo",)):
        return "rotativo"
    if any(token in text for token in ("minimo", "mínimo")):
        return "minimo"
    if any(token in text for token in ("parcial", "parcelo")):
        return "parcial"
    if any(
        token in text
        for token in (
            "total",
            "pago tudo",
            "pago a fatura inteira",
            "pago a fatura toda",
            "pago toda a fatura",
            "fatura toda",
        )
    ):
        return "total"
    return ""


def _infer_main_issue_hypothesis(summary: dict[str, Any]) -> str:
    if summary.get("card_payment_behavior") in {"rotativo", "minimo"}:
        return "high_interest_debt"
    if summary.get("debt_outside_cards") == "yes":
        return "outside_debt_pressure"
    if summary.get("has_emergency_reserve") == "no":
        return "no_emergency_buffer"
    if summary.get("income_extra_type") == "pontual":
        return "income_volatility"
    return summary.get("main_issue_hypothesis", "")


def _push_note(summary: dict[str, Any], note: str) -> None:
    clean_note = (note or "").strip()[:160]
    if not clean_note:
        return
    notes = list(summary.get("notes") or [])
    if clean_note not in notes:
        notes.append(clean_note)
    summary["notes"] = notes[-5:]


def _should_move_to_action_plan(
    summary: dict[str, Any],
    inferred_stage: str,
    question_key: str,
    expected_answer_type: str,
) -> bool:
    if inferred_stage == "action_plan":
        return True
    if (question_key or "").strip() or (expected_answer_type or "").strip():
        return False
    if summary.get("main_issue_hypothesis") in {
        "high_interest_debt",
        "outside_debt_pressure",
        "no_emergency_buffer",
    }:
        if summary.get("has_emergency_reserve") != "unknown" or summary.get("card_payment_behavior"):
            return True
    return False
