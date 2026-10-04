# volatility_breakout_intraday_v1_btc_eth_15m

Run ID: 20261004T145930Z-5bae5d16f71c
Strategy: volatility_breakout_intraday_v1 1.0.0
Code hash: cad120a9800c23380cce3bfe08aac5a43084bde453192ebcddf7f4aaa56ecac5
Git commit: c40d5c4d3e345eda56f34474302f86bd1cfc8109
Backend: StudyBackend v1; independent liquidated periods, causal warmup.
Execution: synthetic; funding is not modelled.
No automatic promising/validated designation or future-profit claim.

## Datasets and periods

- BTCUSDT 15m: 0a6032afe6c1e90ece9fe7f09ad8e7630860343b8433ca7f0d720102b54ffa97 (2020-01-01 00:00:00+00:00 .. 2026-09-26 00:00:00+00:00); SHA256 4cd16c93b3cc5c2c5dcf8c47720f7db4121750efb78c7d2fe0d2e4b2c58c9799
- ETHUSDT 15m: 9d4bcb5a0627a70513522de8d967c52697af68220dba52ce626a9915730e35c8 (2020-01-01 00:00:00+00:00 .. 2026-09-26 00:00:00+00:00); SHA256 81a1a2515b321d29fabe33a1aea83896d8208b063d511438cf09f766357e6e0c
Modes: LONG_ONLY, SHORT_ONLY, LONG_SHORT

```json
{
  "train": {
    "start": "2020-02-01T00:00:00Z",
    "end": "2023-01-01T00:00:00Z"
  },
  "validation": {
    "start": "2023-01-01T00:00:00Z",
    "end": "2025-01-01T00:00:00Z"
  },
  "test": {
    "start": "2025-01-01T00:00:00Z",
    "end": "2026-09-26T00:00:00Z"
  },
  "walk_forward": [],
  "cost_stress": {
    "adverse": {
      "trading_fee_pct": 0.1,
      "slippage_pct": 0.06,
      "spread_pct": 0.02
    }
  }
}
```

## Counts and predefined filters

```json
{
  "total_backtests": 120,
  "valid_backtests": 120,
  "failed_backtests": 0,
  "filter_rejected_backtests": 0,
  "survivors": 6,
  "configurations": 6,
  "filters": {
    "minimum_trades": 1,
    "maximum_drawdown_pct": 25.0,
    "minimum_profit_factor": null,
    "minimum_sharpe": null,
    "positive_test": false,
    "cost_stress_survival": false
  }
}
```

## Top configurations

Sorted ONLY by TRAIN/base closed_trades, descending; ties use configuration_id, undefined metrics last. Holdouts are descriptive.

```json
[
  {
    "configuration_id": "65d4020d3c04873a",
    "strategy": "volatility_breakout_intraday_v1",
    "strategy_version": "1.0.0",
    "symbol": "ETHUSDT",
    "timeframe": "15m",
    "mode": "LONG_SHORT",
    "parameters": "{\"atr_expansion_factor\": 1.1, \"atr_period\": 14, \"atr_reference_window\": 20, \"breakout_lookback\": 20, \"compression_ratio\": 0.75, \"compression_window\": 60, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"momentum_threshold\": 0.5, \"reward_risk\": 2.0, \"stop_atr_multiplier\": 2.0}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": -8.74741862140982,
    "train_sharpe": -0.7374346889566521,
    "train_max_drawdown_pct": 10.8741274949064,
    "train_profit_factor": 0.8172511022133052,
    "train_closed_trades": 211,
    "train_expectancy": -4.145696029104227,
    "train_long_contribution": -353.4638100327626,
    "train_short_contribution": -521.2780521082292,
    "validation_return_pct": -6.090223995926314,
    "validation_sharpe": -1.1297131254941037,
    "validation_max_drawdown_pct": 8.473323719849574,
    "validation_profit_factor": 0.7694989179446369,
    "validation_closed_trades": 193,
    "validation_expectancy": -3.1555564745731606,
    "validation_long_contribution": -406.94109039904504,
    "validation_short_contribution": -202.081309193575,
    "test_return_pct": -8.832461535912795,
    "test_sharpe": -1.6326707179992532,
    "test_max_drawdown_pct": 10.1320084221698,
    "test_profit_factor": 0.6929774412730656,
    "test_closed_trades": 173,
    "test_expectancy": -5.105469095903346,
    "test_long_contribution": -334.04510807610524,
    "test_short_contribution": -549.2010455151736
  },
  {
    "configuration_id": "e3adf1ded2fcfb74",
    "strategy": "volatility_breakout_intraday_v1",
    "strategy_version": "1.0.0",
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "mode": "LONG_SHORT",
    "parameters": "{\"atr_expansion_factor\": 1.1, \"atr_period\": 14, \"atr_reference_window\": 20, \"breakout_lookback\": 20, \"compression_ratio\": 0.75, \"compression_window\": 60, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"momentum_threshold\": 0.5, \"reward_risk\": 2.0, \"stop_atr_multiplier\": 2.0}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": -11.356027917339928,
    "train_sharpe": -1.1879492310591047,
    "train_max_drawdown_pct": 11.585765345496405,
    "train_profit_factor": 0.7069098014121021,
    "train_closed_trades": 206,
    "train_expectancy": -5.512634911330034,
    "train_long_contribution": -852.5227230919638,
    "train_short_contribution": -283.0800686420231,
    "validation_return_pct": -5.353947976234686,
    "validation_sharpe": -1.1989623453938885,
    "validation_max_drawdown_pct": 7.720642389364525,
    "validation_profit_factor": 0.7571259587848159,
    "validation_closed_trades": 184,
    "validation_expectancy": -2.909754334910161,
    "validation_long_contribution": -149.6844446763663,
    "validation_short_contribution": -385.7103529471033,
    "test_return_pct": -5.439257296425581,
    "test_sharpe": -1.562736366770373,
    "test_max_drawdown_pct": 5.439257296425585,
    "test_profit_factor": 0.683152768463513,
    "test_closed_trades": 148,
    "test_expectancy": -3.6751738489362245,
    "test_long_contribution": -311.23195512456005,
    "test_short_contribution": -232.6937745180012
  },
  {
    "configuration_id": "578571137bf7a209",
    "strategy": "volatility_breakout_intraday_v1",
    "strategy_version": "1.0.0",
    "symbol": "ETHUSDT",
    "timeframe": "15m",
    "mode": "LONG_ONLY",
    "parameters": "{\"atr_expansion_factor\": 1.1, \"atr_period\": 14, \"atr_reference_window\": 20, \"breakout_lookback\": 20, \"compression_ratio\": 0.75, \"compression_window\": 60, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"momentum_threshold\": 0.5, \"reward_risk\": 2.0, \"stop_atr_multiplier\": 2.0}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": -3.6691200380036593,
    "train_sharpe": -0.4139282499299542,
    "train_max_drawdown_pct": 5.3670588872435925,
    "train_profit_factor": 0.8655713393658072,
    "train_closed_trades": 123,
    "train_expectancy": -2.983024421141212,
    "train_long_contribution": -366.91200380036906,
    "train_short_contribution": 0,
    "validation_return_pct": -4.085203098693036,
    "validation_sharpe": -0.9414181666105363,
    "validation_max_drawdown_pct": 6.809397993196987,
    "validation_profit_factor": 0.7383185179594193,
    "validation_closed_trades": 108,
    "validation_expectancy": -3.7825954617527393,
    "validation_long_contribution": -408.52030986929583,
    "validation_short_contribution": 0,
    "test_return_pct": -3.4104856968157793,
    "test_sharpe": -0.941251494741985,
    "test_max_drawdown_pct": 4.309696479629026,
    "test_profit_factor": 0.7463018170002025,
    "test_closed_trades": 84,
    "test_expectancy": -4.060102020018733,
    "test_long_contribution": -341.04856968157355,
    "test_short_contribution": 0
  },
  {
    "configuration_id": "bf49896e88838b8b",
    "strategy": "volatility_breakout_intraday_v1",
    "strategy_version": "1.0.0",
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "mode": "SHORT_ONLY",
    "parameters": "{\"atr_expansion_factor\": 1.1, \"atr_period\": 14, \"atr_reference_window\": 20, \"breakout_lookback\": 20, \"compression_ratio\": 0.75, \"compression_window\": 60, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"momentum_threshold\": 0.5, \"reward_risk\": 2.0, \"stop_atr_multiplier\": 2.0}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": -2.750332344382933,
    "train_sharpe": -0.33908813431954277,
    "train_max_drawdown_pct": 6.4066404790125615,
    "train_profit_factor": 0.8690778972264809,
    "train_closed_trades": 111,
    "train_expectancy": -2.477776886831508,
    "train_long_contribution": 0,
    "train_short_contribution": -275.0332344382974,
    "validation_return_pct": -3.8633134668144664,
    "validation_sharpe": -1.2355121017793402,
    "validation_max_drawdown_pct": 4.971539063657948,
    "validation_profit_factor": 0.6405178819690257,
    "validation_closed_trades": 80,
    "validation_expectancy": -4.829141833517859,
    "validation_long_contribution": 0,
    "validation_short_contribution": -386.3313466814287,
    "test_return_pct": -2.365593297173041,
    "test_sharpe": -0.8603977710513574,
    "test_max_drawdown_pct": 2.4279192359425177,
    "test_profit_factor": 0.737893927826282,
    "test_closed_trades": 71,
    "test_expectancy": -3.3318215453141513,
    "test_long_contribution": 0,
    "test_short_contribution": -236.55932971730473
  },
  {
    "configuration_id": "e9a6b0dc17b426eb",
    "strategy": "volatility_breakout_intraday_v1",
    "strategy_version": "1.0.0",
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "mode": "LONG_ONLY",
    "parameters": "{\"atr_expansion_factor\": 1.1, \"atr_period\": 14, \"atr_reference_window\": 20, \"breakout_lookback\": 20, \"compression_ratio\": 0.75, \"compression_window\": 60, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"momentum_threshold\": 0.5, \"reward_risk\": 2.0, \"stop_atr_multiplier\": 2.0}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": -8.84905193393064,
    "train_sharpe": -1.49341211937641,
    "train_max_drawdown_pct": 9.45235318344329,
    "train_profit_factor": 0.5451252817081851,
    "train_closed_trades": 95,
    "train_expectancy": -9.314791509400639,
    "train_long_contribution": -884.9051933930607,
    "train_short_contribution": 0,
    "validation_return_pct": -1.550532470921917,
    "validation_sharpe": -0.46809583760248097,
    "validation_max_drawdown_pct": 3.670202161784165,
    "validation_profit_factor": 0.8679241413564658,
    "validation_closed_trades": 104,
    "validation_expectancy": -1.490896606655698,
    "validation_long_contribution": -155.05324709219258,
    "validation_short_contribution": 0,
    "test_return_pct": -3.148144574189504,
    "test_sharpe": -1.4202731925434893,
    "test_max_drawdown_pct": 3.349375097547327,
    "test_profit_factor": 0.6279697768165484,
    "test_closed_trades": 77,
    "test_expectancy": -4.088499446999297,
    "test_long_contribution": -314.81445741894584,
    "test_short_contribution": 0
  },
  {
    "configuration_id": "fc9de4a0fc0a744d",
    "strategy": "volatility_breakout_intraday_v1",
    "strategy_version": "1.0.0",
    "symbol": "ETHUSDT",
    "timeframe": "15m",
    "mode": "SHORT_ONLY",
    "parameters": "{\"atr_expansion_factor\": 1.1, \"atr_period\": 14, \"atr_reference_window\": 20, \"breakout_lookback\": 20, \"compression_ratio\": 0.75, \"compression_window\": 60, \"ema_period\": 100, \"ema_slope_lookback\": 3, \"momentum_threshold\": 0.5, \"reward_risk\": 2.0, \"stop_atr_multiplier\": 2.0}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": -5.271727696778106,
    "train_sharpe": -0.6402418588985674,
    "train_max_drawdown_pct": 7.090278469027554,
    "train_profit_factor": 0.7601634422770709,
    "train_closed_trades": 88,
    "train_expectancy": -5.990599655429744,
    "train_long_contribution": 0,
    "train_short_contribution": -527.1727696778174,
    "validation_return_pct": -2.090417077988127,
    "validation_sharpe": -0.626832756078432,
    "validation_max_drawdown_pct": 2.835842950162316,
    "validation_profit_factor": 0.8134766593637929,
    "validation_closed_trades": 85,
    "validation_expectancy": -2.459314209397912,
    "validation_long_contribution": 0,
    "validation_short_contribution": -209.0417077988225,
    "test_return_pct": -5.613422153791802,
    "test_sharpe": -1.3218135920515552,
    "test_max_drawdown_pct": 6.639540970223642,
    "test_profit_factor": 0.6478552218281438,
    "test_closed_trades": 89,
    "test_expectancy": -6.307215903136836,
    "test_long_contribution": 0,
    "test_short_contribution": -561.3422153791784
  }
]
```

## Walk-forward and cost stress

Walk-forward selects each fold on TRAIN/base; only selected fold TEST rows are OOS results. Medians below are descriptive, not a compounded portfolio.

Median metrics across configurations (including TRAIN/validation/final TEST):

```csv
period,scenario,return_pct,cagr_pct,sharpe,sortino,max_drawdown_pct,profit_factor,win_rate_pct,expectancy,closed_trades,average_close_exposure_pct,fees_paid,slippage_cost_closed_trades,funding_pnl,long_contribution,short_contribution

diagnostic_2020,adverse,-5.137567801102893,-5.584498125093434,-2.842830775460489,-2.97120612863085,5.815371291724967,0.29889600141864925,22.32075471698113,-17.584843969589894,31.0,0.2663235564531509,152.52751388956563,91.51644184068434,,-349.52043138038107,-463.48944334455126

diagnostic_2020,base,-4.431595519231169,-4.818675229400348,-2.579454609803702,-2.7555916799381164,5.244926130056925,0.37508043394395835,22.9874213836478,-14.11066268515234,31.5,0.25974336802155185,78.01168382390566,46.806992352635035,,-254.47994995075783,-406.1129188775351

diagnostic_2021,adverse,-0.6881567772257902,-0.6881567772257902,-0.1579857859175853,-0.23058892409395498,4.079314643715861,0.9465812320806354,37.244897959183675,-1.442270473736604,43.5,0.4668716733146227,213.4472453279156,128.0683395916159,,-149.6709569761888,54.086282762962725

diagnostic_2021,base,1.1198255859627415,1.1198255859627415,0.3344482057725508,0.6401418164931431,3.645798828892127,1.1180922471340549,38.265306122448976,2.956170820236304,43.5,0.5457248180262285,107.86125566143855,64.71675341215564,,0.0,149.74850994286552

diagnostic_2022,adverse,-3.856724746469914,-3.856724746469914,-1.6872479831206304,-2.1829169183190746,4.906505013656974,0.6515228893895638,31.64750957854406,-8.188301656487592,54.5,0.517015279415598,267.5906512629027,160.55442471218674,,-283.4012201897995,-174.66809266174417

diagnostic_2022,base,-1.807609761574419,-1.807609761574419,-0.792961297585507,-1.1651263557098295,2.8673940113073746,0.8293809118978512,32.95880149812734,-3.638788471778661,54.0,0.576522046844539,134.27729444684982,80.56638522425689,,-92.07243186994202,0.0

diagnostic_2023,adverse,-3.427248161763136,-3.427248161763136,-1.9254195323837366,-2.463523887974422,3.775448494330772,0.5758858868314998,32.64790764790765,-5.67618825525542,52.0,0.38289369273374796,256.91414618379565,154.1485723405079,,-206.63425056211526,-256.6524849221205

diagnostic_2023,base,-1.1180862059552987,-1.1180862059552987,-0.6146232089050523,-0.9232438431074572,2.4072189504643324,0.840569362041555,34.84848484848485,-1.743265839706023,51.5,0.3876362667967541,128.65240990346805,77.19146700516549,,0.0,-89.15760575550632

diagnostic_2024,adverse,-5.09035095564252,-5.076802658288832,-2.4695627748879483,-3.1874439550486757,5.958013194600445,0.5320919514223608,30.15677491601344,-7.947446328211949,54.5,0.4614623943563132,262.8691098789602,157.72143982116762,,-485.8903144506435,-243.79676431920882

diagnostic_2024,base,-2.0961666541077006,-2.0905026569908722,-0.9731246377155343,-1.4742844726640398,3.718382517221154,0.7854686223166791,33.22141560798548,-2.812103897955698,54.5,0.459376535777669,133.3041775781439,79.9825025767255,,-163.45842620241717,-92.9505634946307

diagnostic_2025,adverse,-4.919869169318636,-4.919869169318636,-2.398731472829244,-3.1401542864597682,5.104528813811115,0.49891433590885687,27.1875,-9.329962772015584,49.0,0.5391190158598187,238.72358005732718,143.23412803650155,,-430.8396902408647,-267.70704494246013

diagnostic_2025,base,-2.819971465961352,-2.819971465961352,-1.3936170587682026,-1.9932487709897693,3.2381205006330873,0.6691390198725834,27.35363924050633,-5.542280969218633,48.5,0.5680652856880242,119.73247828725536,71.83948013189234,,-271.8597928947289,-163.95711724159398

diagnostic_2026,adverse,-2.932880086198991,-3.9713095778135585,-2.4179870341859093,-2.9123132129882148,3.6155694226180297,0.5106750285070943,32.84313725490196,-6.480964120014654,40.0,0.5946568926974976,196.11730687859833,117.67037366135554,,-199.91499154706224,-169.92631482948474

diagnostic_2026,base,-0.8544167032890904,-1.1618236211718036,-0.6221071529450146,-0.8892416013041088,1.780384953590973,0.8416352640693348,35.59577677224736,-1.9571253431196456,40.5,0.6337064099056138,100.07029656831037,60.04217593059241,,-25.05805847077061,-72.91223221945963

test,adverse,-8.505579840281136,-5.001032837526504,-2.6378786263854774,-3.2010082662074124,8.921535207821613,0.48970408283018885,29.305266805266804,-8.05071680847529,86.5,0.527894087744034,414.0333198545343,248.41993876699652,,-617.2185345030734,-429.1726496356312

test,base,-4.42487149662068,-2.577221103630217,-1.3710433922975223,-1.900999754194293,4.8744768880273055,0.6880651048682893,32.41339931480776,-4.0743007335090144,86.5,0.5532963343666928,210.87009073960036,126.52204470855398,,-313.02320627175294,-234.62655211765298

train,adverse,-10.547004385504477,-3.751538041176672,-1.274234651332819,-1.775019671527939,11.332634676111633,0.6581924663365328,30.72048564886309,-8.35287847333155,116.5,0.4225024432514857,550.9741013184305,330.5845272552479,,-869.1146147926033,-656.5702501646349

train,base,-7.0095731590939625,-2.463768320881793,-0.6888382739276098,-1.029855603350779,8.271315826235423,0.788707272245188,31.43939393939394,-4.829165470217131,117.0,0.44573199179605105,283.60790843732013,170.1647619842808,,-360.1879069165658,-279.05665154016026

validation,adverse,-7.322627755944744,-3.7261762833472547,-2.139758559292181,-2.7426913557431947,8.48089226801881,0.5475210043810623,30.927041030667972,-6.827467551550146,106.5,0.38919730230604865,513.6429933470238,308.18585519897476,,-672.0468916645116,-503.54271770859157

validation,base,-3.974258282753751,-2.0045730330935596,-1.0355656460523202,-1.5270498442676352,5.890468528427467,0.7633124383647264,32.88465870691597,-3.0326554047416607,106.0,0.39855873370825035,261.74028538573964,157.04418836447508,,-152.36884588427944,-205.56150849619877
```

## Failure reasons

```json
{}
```

## Parameter patterns among filter survivors

```json
{
  "ema_period": {
    "most_common_20": {
      "100": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "ema_slope_lookback": {
    "most_common_20": {
      "3": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "compression_window": {
    "most_common_20": {
      "60": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "compression_ratio": {
    "most_common_20": {
      "0.75": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "breakout_lookback": {
    "most_common_20": {
      "20": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "atr_period": {
    "most_common_20": {
      "14": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "atr_reference_window": {
    "most_common_20": {
      "20": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "atr_expansion_factor": {
    "most_common_20": {
      "1.1": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "momentum_threshold": {
    "most_common_20": {
      "0.5": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "stop_atr_multiplier": {
    "most_common_20": {
      "2.0": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "reward_risk": {
    "most_common_20": {
      "2.0": 6
    },
    "distinct_values": 1,
    "other_configurations": 0
  }
}
```

## Files generated

- experiment_snapshot.yaml: original YAML; relative references resolved in resolved.json
- resolved.json: frozen strategy, defaults, parameters and dataset manifests
- environment.json / provenance.json / plan.json: code/environment and experiment
- ledger.sqlite: individual backtest lifecycle and result hashes
- metrics.csv: all periods, costs, metrics and PASS/FAIL reasons
- leaderboard.csv: configurations ranked on TRAIN/base with holdout columns
- summary.json / summary.md / ai_summary.md: compact research summaries
- run.json / outcome.json: immutable start and terminal records
- <backtest_id>/result.json and equity.parquet: trades, rejections, metrics, equity

Historical results do not establish future profitability.
