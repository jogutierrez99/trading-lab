"""Reproducible direction comparisons; no retrospective choice of a winning mode."""

import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from quant_lab.cross_market_study import clean_json
from quant_lab.experiments import write_json
from quant_lab.study_report import fmt, markdown


def finalize(store,rows):
    folder=store.path
    table=pd.DataFrame(rows)
    table.to_csv(folder/"metrics.csv",index=False)
    strategy=table[table.kind=="strategy"]
    full=strategy[(strategy.partition=="full")&(strategy.costs=="base")].copy()
    costs=[]
    keys=["asset","timeframe","variant","mode"]
    for key,group in strategy.groupby(keys+["partition"]):
        g=group.set_index("costs")
        if set(g.index)!={"zero","base","adverse"}:
            raise ValueError("Incomplete cost reruns")
        costs.append(dict(zip(keys+["partition"],key,strict=True))|{
            "zero_to_base_drag":g.loc["zero","return_pct"]-g.loc["base","return_pct"],
            "base_to_adverse_drag":g.loc["base","return_pct"]-g.loc["adverse","return_pct"],
            "zero":g.loc["zero","return_pct"],"base":g.loc["base","return_pct"],"adverse":g.loc["adverse","return_pct"],
            "note":"Complete reruns; ZERO disables funding too. Separate fees/slippage/spread/funding columns allow attribution on actual trades; rerun drag is not pure fee subtraction."})
    write_json(folder/"cost_analysis.json",clean_json(costs))
    wf=strategy[strategy.partition.str.startswith("wf_")].copy()
    wf["fold"]=wf.partition.str[3:5].astype(int)
    wf["role"]=wf.partition.str[-4:]
    wf_summary=[]
    for key,g in wf[wf.role=="test"].groupby(keys+["costs"]):
        returns=g.sort_values("fold").return_pct
        wf_summary.append(dict(zip(keys+["costs"],key,strict=True))|{
            "folds":len(g),"positive_fold_ratio":float((returns>0).mean()),
            "median_test_return_pct":float(returns.median()),"worst_test_return_pct":float(returns.min()),
            "chained_test_return_pct":float(((1+returns/100).prod()-1)*100),
            "test_trades":int(g.closed_trades.sum()),
            "note":"TEST only, non-overlapping3-month windows. Chained percentage diagnostic on reset accounts, not an executed portfolio; training never enters the aggregate."})
    write_json(folder/"walk_forward.json",clean_json({"test_summary":wf_summary,"windows":wf.to_dict("records")}))
    classifications={}
    comparison=[]
    diagnostics={name:{} for name in ("entry_quality","time_to_edge","regime_analysis")}
    decompositions=[]
    for row in full.to_dict("records"):
        same=strategy
        for k in keys:
            same=same[same[k]==row[k]]
        parts=same[same.costs=="base"].set_index("partition")
        cost=next(c for c in costs if all(c[k]==row[k] for k in keys) and c["partition"]=="full")
        fold=next(w for w in wf_summary if all(w[k]==row[k] for k in keys) and w["costs"]=="base")
        flags=["DIAGNOSTIC_ONLY","MARGIN_MODEL_ASSUMED"]
        if row["closed_trades"]<30 or parts.loc["final_holdout","closed_trades"]<30:
            flags.append("INSUFFICIENT_DATA")
        if cost["zero"]>0>=cost["base"]:
            flags.append("FAILED_AFTER_COSTS")
        if cost["base"]>0>=cost["adverse"]:
            flags.append("COST_SENSITIVE")
        if any(parts.loc[p,"return_pct"]<=0 for p in ("validation","test","final_holdout")):
            flags.append("FAILED_TEMPORAL_VALIDATION")
        elif row["return_pct"]>0 and (row["profit_factor"] or 0)>1 and (row["sharpe"] or 0)>0 and parts.loc["final_holdout","closed_trades"]>=30 and fold["positive_fold_ratio"]>=.5:
            flags.append("PROMISING_BUT_UNCONFIRMED")
        key="/".join(str(row[k]) for k in keys)
        classifications[key]=flags
        item=row|{"cost_drag":cost["zero_to_base_drag"],"zero":cost["zero"],"base":cost["base"],"adverse":cost["adverse"],"classification":";".join(flags),"wf_positive_fold_ratio":fold["positive_fold_ratio"]}
        item.update({p:float(parts.loc[p,"return_pct"]) for p in ("train","validation","test","final_holdout")})
        long_only=full[(full.asset==row["asset"])&(full.timeframe==row["timeframe"])&(full.variant==row["variant"])&(full["mode"]=="LONG_ONLY")].iloc[0]
        item["short_incremental_value"]=row["return_pct"]-long_only.return_pct if row["mode"]=="LONG_SHORT" else None
        comparison.append(item)
        doc=json.loads((folder/row["experiment_id"]/"result.json").read_text())
        for target,source in (("entry_quality","entry_quality"),("time_to_edge","time_to_edge"),("regime_analysis","regimes")):
            diagnostics[target][key]=doc[source]
        if row["mode"]=="LONG_SHORT":
            decompositions.append({k:row[k] for k in keys}|{k:v for k,v in row.items() if k.startswith(("long_","short_"))}|{"short_incremental_value":item["short_incremental_value"]})
    compare=pd.DataFrame(comparison)
    compare.to_csv(folder/"direction_comparison.csv",index=False)
    pd.DataFrame(decompositions).to_csv(folder/"long_short_decomposition.csv",index=False)
    columns=keys+["partition","costs","funding_pnl","funding_cost","long_funding_pnl","short_funding_pnl","funding_as_pct_gross_profit","gross_profit_denominator"]
    strategy[columns].to_csv(folder/"funding_analysis.csv",index=False)
    write_json(folder/"classifications.json",classifications)
    for name,content in diagnostics.items():
        write_json(folder/(name+".json"),content)
    draw_charts(folder,compare,diagnostics,wf_summary)
    write_summary(folder,compare,diagnostics,wf_summary)


def draw_charts(folder,df,diagnostics,wf):
    charts=folder/"charts"
    plt.rcParams.update({"figure.dpi":120,"font.size":9})
    # Equity charts for EVERY variant/asset/timeframe; none selected on results.
    for (asset,tf,variant),group in df.groupby(["asset","timeframe","variant"]):
        curves={row["mode"]:pd.read_parquet(folder/"equity"/(row["experiment_id"]+".parquet")).equity for row in group.to_dict("records")}
        ax=pd.DataFrame(curves).plot(figsize=(12,5))
        ax.set_title(f"{asset} {tf} variant{variant} | BASE, funding included")
        ax.set_ylabel("USDT, independent10000 accounts")
        ax.figure.tight_layout()
        name=f"long_short_equity_comparison_{asset}_{tf}_{variant}.png"
        ax.figure.savefig(charts/name)
        if (asset,tf,variant)==("BTCUSDT","4h","A"):
            ax.figure.savefig(charts/"long_short_equity_comparison.png")
        plt.close(ax.figure)
    for mode in ("LONG_ONLY","SHORT_ONLY","LONG_SHORT"):
        group=df[df["mode"]==mode]
        curves={f"{r.asset}/{r.timeframe}/{r.variant}":pd.read_parquet(folder/"equity"/(r.experiment_id+".parquet")).equity for r in group.itertuples()}
        ax=pd.DataFrame(curves).plot(figsize=(13,7),alpha=.65)
        ax.set_title(mode+" | all frozen configurations, BASE")
        ax.legend(fontsize=7,ncol=3)
        ax.figure.tight_layout();ax.figure.savefig(charts/(mode+"_equity.png"));plt.close(ax.figure)
    for column,name in (("return_pct","direction_comparison"),("funding_pnl","funding_impact"),("long_mfe_mae","long_MFE_MAE"),("short_mfe_mae","short_MFE_MAE")):
        work=df.copy();work["configuration"]=work.asset+"/"+work.timeframe+"/"+work.variant
        ax=work.pivot(index="configuration",columns="mode",values=column).plot.barh(figsize=(12,9))
        ax.set_title(name+" | BASE");ax.figure.tight_layout();ax.figure.savefig(charts/(name+".png"));plt.close(ax.figure)
    both=df[df["mode"]=="LONG_SHORT"].copy()
    both.index=both.asset+"/"+both.timeframe+"/"+both.variant
    for metric in ("pnl","profit_factor","expectancy"):
        ax=both[["long_"+metric,"short_"+metric]].plot.barh(figsize=(12,9))
        ax.set_title("LONG_SHORT directional "+metric);ax.figure.tight_layout();ax.figure.savefig(charts/("long_vs_short_"+metric+".png"));plt.close(ax.figure)
    work=df.copy();work.index=work.asset+"/"+work.timeframe+"/"+work.variant+"/"+work["mode"]
    ax=work[["zero","base","adverse"]].plot.barh(figsize=(13,17))
    ax.set_title("Full reruns by cost scenario; ZERO excludes funding")
    ax.figure.tight_layout();ax.figure.savefig(charts/"cost_comparison.png");plt.close(ax.figure)
    w=pd.DataFrame(wf);w=w[w.costs=="base"]
    ax=w.groupby("mode").positive_fold_ratio.mean().plot.bar(figsize=(8,5),ylim=(0,1))
    ax.set_title("Mean positive WF TEST-fold ratio; all54 frozen configurations")
    ax.figure.tight_layout();ax.figure.savefig(charts/"walk_forward.png");plt.close(ax.figure)
    values=[]
    for key,report in diagnostics["regime_analysis"].items():
        for regime,pairs in report.get("trend",{}).items():
            for side,stats in pairs.items():values.append({"regime":regime,"side":side,"pnl":stats["pnl"]})
    r=pd.DataFrame(values)
    ax=r.groupby(["regime","side"]).pnl.median().unstack().plot.bar(figsize=(10,5))
    ax.set_title("Median per-account trade PnL attributed at entry regime; not a portfolio")
    ax.figure.tight_layout();ax.figure.savefig(charts/"regime_performance.png");plt.close(ax.figure)


def write_summary(folder,df,diagnostics,wf):
    groups={mode:df[df["mode"]==mode] for mode in ("LONG_ONLY","SHORT_ONLY","LONG_SHORT")}
    def describe(mode):
        g=groups[mode]
        return f"{int((g.return_pct>0).sum())}/{len(g)} positivas; retorno mediano{fmt(g.return_pct.median())}%, Sharpe{fmt(g.sharpe.median())}, PF{fmt(g.profit_factor.median())}, trades{fmt(g.closed_trades.median())}"
    pivot=df.pivot(index=["asset","timeframe","variant"],columns="mode",values="return_pct")
    both=groups["LONG_SHORT"]
    destroyed=both[((both.long_pnl>0)&(both.short_pnl<0))|((both.short_pnl>0)&(both.long_pnl<0))]
    regimes=[]
    for key,report in diagnostics["regime_analysis"].items():
        if not key.endswith("LONG_SHORT"):
            continue
        for label,pairs in report.get("trend",{}).items():
            for side,v in pairs.items():regimes.append({"regime":label,"side":side,**v})
    r=pd.DataFrame(regimes)
    def regime_summary(label):
        g=r[r.regime==label]
        return "; ".join(f"{side}: PnL mediano por cuenta{fmt(v.pnl.median())}, trades medianos{fmt(v.trades.median())}" for side,v in g.groupby("side")) or "sin operaciones"
    stats=df.groupby("variant").agg(positive=("return_pct",lambda x:int((x>0).sum())),median_return=("return_pct","median"),median_sharpe=("sharpe","median"),median_pf=("profit_factor","median"),median_trades=("closed_trades","median"))
    questions=[
        "1. LONG: "+describe("LONG_ONLY")+". Diagnostico, no demostracion de edge futuro.",
        "2. SHORT: "+describe("SHORT_ONLY")+". No se usan precios spot para cortos.",
        f"3. LONG_SHORT supera el retorno de LONG_ONLY en{int((pivot.LONG_SHORT>pivot.LONG_ONLY).sum())}/18 casos y de SHORT_ONLY en{int((pivot.LONG_SHORT>pivot.SHORT_ONLY).sum())}/18. Revisar tambien DD, Sharpe y PF; mayor retorno no prueba superioridad.",
        f"4. En LONG_SHORT, la contribucion long supera la short en{int((both.long_pnl>both.short_pnl).sum())}/18 cuentas. La descomposicion por cuenta esta en long_short_decomposition.csv; no se suman cuentas.",
        f"5. {len(destroyed)}/18 cuentas combinadas tienen una direccion positiva y la otra negativa. Ver contribuciones e incremental short; las cuentas independientes no son aditivas por sizing y oportunidades incompatibles.",
        "6. BTC/ETH: "+"; ".join(f"{a}: {int((g.return_pct>0).sum())}/{len(g)} positivas, retorno mediano{fmt(g.return_pct.median())}%" for a,g in df.groupby("asset"))+".",
        "7. Timeframes: "+"; ".join(f"{t}: retorno mediano{fmt(g.return_pct.median())}%, Sharpe{fmt(g.sharpe.median())}" for t,g in df[df.timeframe.isin(["1h","4h"])].groupby("timeframe"))+".",
        f"8. 1d: trades medianos{fmt(df[df.timeframe=='1d'].closed_trades.median())}; pocas operaciones limitan cualquier conclusion.",
        f"9. Costes: drag ZERO-BASE mediano{fmt(df.cost_drag.median())} puntos. ZERO tambien excluye funding; los componentes reales estan separados en CSV.",
        f"10. Funding: historico real incluido; PnL funding mediano por cuenta{fmt(df.funding_pnl.median())}USDT. Es positivo si se recibe y negativo si se paga. Mark-open es proxy con offsets<1s; margen historico por tiers no reconstruido.",
        f"11. MFE/MAE mediano en cuentas combinadas: LONG{fmt(both.long_mfe_mae.median())}, SHORT{fmt(both.short_mfe_mae.median())}. Cotas intrabar horarias; no recorrido exacto.",
        f"12. Expectancy mediana combinada: LONG{fmt(both.long_expectancy.median())}USDT/trade, SHORT{fmt(both.short_expectancy.median())}USDT/trade.",
        "13. BULL: "+regime_summary("BULL")+".",
        "14. BEAR: "+regime_summary("BEAR")+".",
        "15. SIDEWAYS: "+regime_summary("SIDEWAYS")+".",
        f"16. {int((df.closed_trades>=30).sum())}/54 configuraciones tienen>=30 trades FULL/BASE. La clasificacion exige tambien muestra suficiente en holdout.",
        "17. Walk-forward: "+"; ".join(f"{mode}: media de folds TEST positivos{fmt(pd.DataFrame(wf).query('mode == @mode and costs == \"base\"').positive_fold_ratio.mean()*100)}%" for mode in groups)+". No incluye TRAIN en el agregado.",
        f"18. Holdout: {int((df.final_holdout>0).sum())}/54 positivos BASE. Los mercados subyacentes ya se observaron; validacion temporal diagnostica, no OOS puro ni paper.",
        "19. Variantes: la tabla comparativa siguiente muestra todas. No se selecciona un ganador por retorno ni se ajusta ninguna variante; valorar frecuencia, validacion y costes conjuntamente.",
        "20. Seguir investigando requiere una hipotesis nueva predefinida y datos futuros. La asimetria medida y los casos de contribucion negativa identifican preguntas; no autorizan eliminar retrospectivamente cortos o largos perdedores.",
    ]
    lines=["# Batch006 Bollinger long/short", "",
           "54 configuraciones congeladas; tres variantes y tres modos. Futuros USD-M reales,1x, cuentas independientes10000USDT. Sin live trading ni optimizacion.",
           "Bollinger/RSI/ADX/ATR/EMA conservan barras; time stop72h. Ejecucion y MFE sobre velas1h tambien para señales4h/1d. Funding real; hipotesis de margen aislado y liquidacion no equivalen a simulacion perfecta de Binance.",
           "LONG_SHORT no hace hedge, pyramiding ni reversal en el mismo open. Cada hueco liquida y reinicia features; no se interpolan velas. Los benchmarks son posiciones LONG perpetuas con funding, no spot ni short buy&hold.",
           "Holdout bloqueado hasta completar los splits y folds anteriores. Todos los resultados negativos se retienen. WF train12m/test3m/step3m, sin reoptimizar.","",*questions,"",
           "## Variantes (descriptivo)",stats.to_string(),"",
           "## Matriz completa BASE",markdown(df,["asset","timeframe","variant","mode","train","validation","test","final_holdout","zero","base","adverse","return_pct","sharpe","profit_factor","max_drawdown_pct","closed_trades","long_trades","short_trades","long_pnl","short_pnl","long_mfe_mae","short_mfe_mae","funding_pnl","classification"])]
    (folder/"summary.md").write_text("\n\n".join(lines)+"\n",encoding="utf-8")
