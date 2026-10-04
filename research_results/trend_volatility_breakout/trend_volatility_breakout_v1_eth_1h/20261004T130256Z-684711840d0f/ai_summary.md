# trend_volatility_breakout_v1_eth_1h

Run ID: 20261004T130256Z-684711840d0f
Strategy: trend_volatility_breakout_v1 1.0.1
Code hash: 7cd230706e6b2f8e124a219b73159acef8ba8f72ea3d096130a3de5341a95ac4
Git commit: d21d532beceb38c5c5b9054e8f540fe05252cdee
Backend: StudyBackend v1; independent liquidated periods, causal warmup.
Execution: synthetic; funding is not modelled.
No automatic promising/validated designation or future-profit claim.

## Datasets and periods

- ETHUSDT 1h: 1006e4cb8296ab8d1574317f2927c7feb975bbd25a5f195a8c7d97a17d7b70e4 (2020-01-01 00:00:00+00:00 .. 2026-09-26 00:00:00+00:00); SHA256 45d54f213f24b4282a4a5ac972431aafb8d303456e4c202b548ec0e9196fb8ec
Modes: LONG_ONLY, SHORT_ONLY, LONG_SHORT

```json
{
  "train": {
    "start": "2023-06-04T00:00:00Z",
    "end": "2024-07-01T00:00:00Z"
  },
  "validation": {
    "start": "2024-07-01T00:00:00Z",
    "end": "2025-01-01T00:00:00Z"
  },
  "test": {
    "start": "2025-07-01T00:00:00Z",
    "end": "2026-09-26T00:00:00Z"
  },
  "walk_forward": [
    {
      "train": {
        "start": "2023-07-01T00:00:00Z",
        "end": "2024-07-01T00:00:00Z"
      },
      "test": {
        "start": "2024-07-01T00:00:00Z",
        "end": "2024-10-01T00:00:00Z"
      }
    },
    {
      "train": {
        "start": "2023-10-01T00:00:00Z",
        "end": "2024-10-01T00:00:00Z"
      },
      "test": {
        "start": "2024-10-01T00:00:00Z",
        "end": "2025-01-01T00:00:00Z"
      }
    },
    {
      "train": {
        "start": "2024-01-01T00:00:00Z",
        "end": "2025-01-01T00:00:00Z"
      },
      "test": {
        "start": "2025-01-01T00:00:00Z",
        "end": "2025-04-01T00:00:00Z"
      }
    },
    {
      "train": {
        "start": "2024-04-01T00:00:00Z",
        "end": "2025-04-01T00:00:00Z"
      },
      "test": {
        "start": "2025-04-01T00:00:00Z",
        "end": "2025-07-01T00:00:00Z"
      }
    }
  ],
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
  "total_backtests": 6072,
  "valid_backtests": 6072,
  "failed_backtests": 0,
  "filter_rejected_backtests": 0,
  "survivors": 432,
  "configurations": 432,
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

Sorted ONLY by TRAIN/base sharpe, descending; ties use configuration_id, undefined metrics last. Holdouts are descriptive.

```json
[
  {
    "configuration_id": "d4b93a5f10ce0abf",
    "strategy": "trend_volatility_breakout_v1",
    "strategy_version": "1.0.1",
    "symbol": "ETHUSDT",
    "timeframe": "1h",
    "mode": "LONG_ONLY",
    "parameters": "{\"atr_expansion_threshold\": 1.0, \"atr_length\": 14, \"atr_reference_length\": 50, \"atr_stop_multiplier\": 2.5, \"breakout_length\": 50, \"reward_risk\": 2.5, \"slope_lookback\": 5, \"trend_length\": 200}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": 5.953538921958423,
    "train_sharpe": 0.7676756329464486,
    "train_max_drawdown_pct": 5.406371548367115,
    "train_profit_factor": 1.264354121585127,
    "train_closed_trades": 58,
    "train_expectancy": 10.26472227923851,
    "train_long_contribution": 595.3538921958336,
    "train_short_contribution": 0,
    "validation_return_pct": -1.3870374004323227,
    "validation_sharpe": -0.3351954221770934,
    "validation_max_drawdown_pct": 4.240433614333848,
    "validation_profit_factor": 0.8953007008199257,
    "validation_closed_trades": 28,
    "validation_expectancy": -4.953705001543915,
    "validation_long_contribution": -138.7037400432296,
    "validation_short_contribution": 0,
    "test_return_pct": -2.792347797389816,
    "test_sharpe": -0.25042625402285096,
    "test_max_drawdown_pct": 11.451060851989219,
    "test_profit_factor": 0.9185515048185078,
    "test_closed_trades": 75,
    "test_expectancy": -3.723130396519723,
    "test_long_contribution": -279.2347797389792,
    "test_short_contribution": 0
  },
  {
    "configuration_id": "8881fc2ef0417469",
    "strategy": "trend_volatility_breakout_v1",
    "strategy_version": "1.0.1",
    "symbol": "ETHUSDT",
    "timeframe": "1h",
    "mode": "LONG_ONLY",
    "parameters": "{\"atr_expansion_threshold\": 1.0, \"atr_length\": 14, \"atr_reference_length\": 50, \"atr_stop_multiplier\": 2.5, \"breakout_length\": 50, \"reward_risk\": 2.5, \"slope_lookback\": 5, \"trend_length\": 100}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": 5.399454904369705,
    "train_sharpe": 0.6946299453339063,
    "train_max_drawdown_pct": 5.406371486216777,
    "train_profit_factor": 1.2280139832600172,
    "train_closed_trades": 62,
    "train_expectancy": 8.708798232854386,
    "train_long_contribution": 539.9454904369719,
    "train_short_contribution": 0,
    "validation_return_pct": -4.2750786990005345,
    "validation_sharpe": -1.060000400134906,
    "validation_max_drawdown_pct": 5.932025917337671,
    "validation_profit_factor": 0.7272123958223582,
    "validation_closed_trades": 32,
    "validation_expectancy": -13.359620934376684,
    "validation_long_contribution": -427.5078699000539,
    "validation_short_contribution": 0,
    "test_return_pct": -1.8775661950216072,
    "test_sharpe": -0.14084073241838468,
    "test_max_drawdown_pct": 11.406499249905314,
    "test_profit_factor": 0.9467794902882886,
    "test_closed_trades": 78,
    "test_expectancy": -2.4071361474635613,
    "test_long_contribution": -187.75661950215778,
    "test_short_contribution": 0
  },
  {
    "configuration_id": "eaed0ebbb191a18e",
    "strategy": "trend_volatility_breakout_v1",
    "strategy_version": "1.0.1",
    "symbol": "ETHUSDT",
    "timeframe": "1h",
    "mode": "LONG_ONLY",
    "parameters": "{\"atr_expansion_threshold\": 1.0, \"atr_length\": 20, \"atr_reference_length\": 50, \"atr_stop_multiplier\": 2.5, \"breakout_length\": 50, \"reward_risk\": 2.5, \"slope_lookback\": 5, \"trend_length\": 200}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": 3.767505904747015,
    "train_sharpe": 0.5253754150573445,
    "train_max_drawdown_pct": 4.947804359846588,
    "train_profit_factor": 1.1600028238096771,
    "train_closed_trades": 61,
    "train_expectancy": 6.176239188109925,
    "train_long_contribution": 376.7505904747054,
    "train_short_contribution": 0,
    "validation_return_pct": -0.5763719840070403,
    "validation_sharpe": -0.14059289735268624,
    "validation_max_drawdown_pct": 4.537946222295997,
    "validation_profit_factor": 0.9493858592934153,
    "validation_closed_trades": 25,
    "validation_expectancy": -2.3054879360280065,
    "validation_long_contribution": -57.63719840070016,
    "validation_short_contribution": 0,
    "test_return_pct": -0.3005594406843781,
    "test_sharpe": 0.0014910582885762655,
    "test_max_drawdown_pct": 11.515566101798974,
    "test_profit_factor": 0.990510001259586,
    "test_closed_trades": 72,
    "test_expectancy": -0.4174436676171701,
    "test_long_contribution": -30.055944068436247,
    "test_short_contribution": 0
  },
  {
    "configuration_id": "d7d2dca0726a7e3f",
    "strategy": "trend_volatility_breakout_v1",
    "strategy_version": "1.0.1",
    "symbol": "ETHUSDT",
    "timeframe": "1h",
    "mode": "LONG_SHORT",
    "parameters": "{\"atr_expansion_threshold\": 1.0, \"atr_length\": 14, \"atr_reference_length\": 50, \"atr_stop_multiplier\": 2.5, \"breakout_length\": 50, \"reward_risk\": 2.5, \"slope_lookback\": 5, \"trend_length\": 200}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": 4.987298769605797,
    "train_sharpe": 0.5183021757651789,
    "train_max_drawdown_pct": 8.540929490128994,
    "train_profit_factor": 1.1310832398196993,
    "train_closed_trades": 98,
    "train_expectancy": 5.08908037714876,
    "train_long_contribution": 677.996940896908,
    "train_short_contribution": -179.26706393632946,
    "validation_return_pct": 1.5902055035862395,
    "validation_sharpe": 0.3378263070381553,
    "validation_max_drawdown_pct": 8.7746281245084,
    "validation_profit_factor": 1.05365177831992,
    "validation_closed_trades": 60,
    "validation_expectancy": 2.6503425059768886,
    "validation_long_contribution": -142.77330861123195,
    "validation_short_contribution": 301.7938589698453,
    "test_return_pct": -8.298901435554084,
    "test_sharpe": -0.5806022551944626,
    "test_max_drawdown_pct": 15.939241289323796,
    "test_profit_factor": 0.8674825301126473,
    "test_closed_trades": 129,
    "test_expectancy": -6.433256926786025,
    "test_long_contribution": -429.2931780731596,
    "test_short_contribution": -400.5969654822376
  },
  {
    "configuration_id": "70fb724e086b59be",
    "strategy": "trend_volatility_breakout_v1",
    "strategy_version": "1.0.1",
    "symbol": "ETHUSDT",
    "timeframe": "1h",
    "mode": "LONG_SHORT",
    "parameters": "{\"atr_expansion_threshold\": 1.0, \"atr_length\": 20, \"atr_reference_length\": 50, \"atr_stop_multiplier\": 2.5, \"breakout_length\": 50, \"reward_risk\": 2.5, \"slope_lookback\": 5, \"trend_length\": 200}",
    "filter_status": "PASS",
    "reason": "",
    "train_return_pct": 4.5389953391268945,
    "train_sharpe": 0.5128148877975742,
    "train_max_drawdown_pct": 8.821757921662758,
    "train_profit_factor": 1.1147252136145613,
    "train_closed_trades": 105,
    "train_expectancy": 4.322852703930449,
    "train_long_contribution": 477.34134071338303,
    "train_short_contribution": -23.44180680068583,
    "validation_return_pct": 3.0777447562302163,
    "validation_sharpe": 0.6275045653688389,
    "validation_max_drawdown_pct": 7.063553232950051,
    "validation_profit_factor": 1.115650780264118,
    "validation_closed_trades": 56,
    "validation_expectancy": 5.495972778982363,
    "validation_long_contribution": -58.28941021327411,
    "validation_short_contribution": 366.06388583628643,
    "test_return_pct": -3.182363064712568,
    "test_sharpe": -0.18447643994852855,
    "test_max_drawdown_pct": 13.488788332987484,
    "test_profit_factor": 0.9486449220148133,
    "test_closed_trades": 129,
    "test_expectancy": -2.4669481121802415,
    "test_long_contribution": -21.808111219526275,
    "test_short_contribution": -296.4281952517249
  }
]
```

## Walk-forward and cost stress

Walk-forward selects each fold on TRAIN/base; only selected fold TEST rows are OOS results. Medians below are descriptive, not a compounded portfolio.

Median metrics across configurations (including TRAIN/validation/final TEST):

```csv
period,scenario,return_pct,cagr_pct,sharpe,sortino,max_drawdown_pct,profit_factor,win_rate_pct,expectancy,closed_trades,average_close_exposure_pct,fees_paid,slippage_cost_closed_trades,funding_pnl,long_contribution,short_contribution

test,adverse,-3.7494017033315954,-3.038816435649605,-0.47514317950325435,-0.7685315618323743,9.877332722589088,0.8864470991336302,35.67892503536068,-4.037868461278962,86.5,3.563642901463453,433.2155267715372,259.92971069015596,,-271.76959704333785,0.0

test,base,0.5503289541859413,0.44416154131022845,0.09725056204992852,0.17237988693471887,7.920891577228991,1.0148125340193483,36.5905552672548,0.5714550379269495,86.0,3.6169512576470417,220.86895385905856,132.5214605041971,,0.0,0.0

train,adverse,-8.2968013346305,-7.729160865233991,-1.6373092651745824,-2.288023409556182,10.466383107797185,0.6739310576660047,32.60269036752342,-10.69347811115895,73.0,3.8671446099967963,346.8417056449188,208.10504131100777,,-368.8311417150675,-663.6406171895385

train,base,-5.441746163903688,-5.064032593872408,-0.9624736299675853,-1.4476956591897356,8.298104265791116,0.7931120781672949,34.04255319148936,-6.510382547513538,74.0,3.8870770615369343,176.86136810124282,106.11679625532227,,-110.04045838224613,-432.7069479319914

validation,adverse,-1.457925708836133,-2.8713366912248626,-0.3987340219498553,-0.6166783254751433,6.012112641016688,0.9099812057084806,35.714285714285715,-3.7599709753109405,37.0,3.177278986780567,181.93441691958566,109.16067277878895,,0.0,0.0

validation,base,0.13831893492700642,0.27456953239507476,0.07642005775330411,0.12636013807722585,5.314639263600946,1.0093827473756296,36.58536585365854,0.4064698578699233,37.0,3.216679945015472,91.73036360101429,55.03825470508427,,0.0,0.0

wf_0_test,adverse,0.610652342748863,2.444734998383491,0.31289967004249547,0.5634221588837509,5.96650852248756,1.0617342891305472,35.714285714285715,3.213959698678218,19.0,5.025573668571135,92.38518286502926,55.43120132948141,,0.0,61.06523427488614

wf_0_test,base,0.5906063009711859,2.363778640867853,0.30291595902074053,0.5601837192624632,5.721096324427042,1.0576732816662895,35.0,2.9530315048556894,20.0,5.1088448665759305,49.05491739490922,29.432965394616275,,0.0,59.06063009711379

wf_0_train,adverse,-8.164598157741022,-8.143224538686955,-1.6722121437432231,-2.34414462220575,9.729838817399642,0.6645293111798871,32.28287841191067,-11.190464979879271,68.5,3.742428961244379,322.21915768726734,193.33130606413755,,-379.328766800032,-624.2518946321918

wf_0_train,base,-5.555846131795217,-5.541094792475221,-1.0287060356280797,-1.5683251002184375,7.88897762590231,0.766375624325299,33.333333333333336,-7.191764687284493,69.0,3.752824794373892,164.00376932373877,98.4022456468135,,-147.13456095562572,-422.6633976366926

wf_1_test,adverse,-1.6493102006143623,-6.385060646237384,-0.9099381244481919,-1.2819866474360642,5.400258757218745,0.8020203422154462,26.666666666666668,-10.995401337429334,16.0,5.82326420718607,80.09947522915674,48.05966266162981,,-188.83559796331164,0.0

wf_1_test,base,-1.0847719325350225,-4.234939140868132,-0.5761717260810673,-0.838929144858975,4.918924385330936,0.8556443392414731,28.571428571428573,-7.748370946678963,16.0,5.838144292046402,40.17840169218094,24.10703382713552,,-136.76206538543548,0.0

wf_1_train,adverse,-6.208675629729033,-6.192248454907217,-1.150286089823612,-1.6461199006045986,8.713372513394026,0.7512577201692694,34.285714285714285,-8.498592593664858,73.0,3.7780007348305054,345.5855840097549,207.351246120706,,-380.0748821669896,-332.45204627549515

wf_1_train,base,-3.2715261343005455,-3.2627349744389464,-0.5772324920098821,-0.9012939545758671,7.087543145755404,0.8596611701387014,35.0,-4.566048052136795,73.0,3.8256226571798795,176.65701366852318,105.99416686210282,,-111.86784792953462,-71.44000326142465

wf_2_test,adverse,-0.7626023002237026,-3.0569303738813947,-0.9074141165333156,-1.181443742331636,6.801559735450066,0.8086009145210987,40.0,-11.325382443250115,17.0,5.724943801011929,75.46811891840385,45.2810222173924,,-76.26023002237312,162.6952745410281

wf_2_test,base,-0.6216105675139305,-2.497136715948989,-0.7293631555276576,-0.9761199682684224,6.717224824238001,0.8479041863266852,40.0,-8.826252293501023,17.0,5.796595420743663,38.12017097687162,22.87213715528034,,-62.1610567513941,205.7898810272091

wf_2_train,adverse,-3.4884797195803454,-3.4791161188983954,-0.48701274844763165,-0.7489797807229907,7.905567931167029,0.8873432643882581,36.650165016501646,-4.35065487769498,72.5,3.8189266530609505,352.1548746503928,211.29301617016557,,0.0,-109.34273479962624

wf_2_train,base,-0.06775361854792772,-0.06756856232053576,0.024151005549623537,0.03747714266665024,6.522157032121322,0.9969301045165546,37.5,-0.10805211937293216,72.5,3.8159687548685683,178.86683655563928,107.32011616925563,,0.0,0.0

wf_3_test,adverse,0.3436942112845287,1.3857031995344382,0.18212470290351132,0.3219144564969198,4.314308901192017,1.0245565444720353,35.8974358974359,0.8812672084220372,18.0,2.7574548241546695,87.0772996735947,52.246282016472804,,298.14905301179033,-263.7796318833309

wf_3_test,base,1.644193438355246,6.7598921980860815,0.6642544952744333,1.2419903962920649,3.8559589644082926,1.1239539635310518,35.8974358974359,4.2158806111673135,18.0,2.6918703393517687,43.726498714663805,26.235872870368983,,374.74592118325194,-210.3265773477267

wf_3_train,adverse,-0.5823882593541829,-0.5823882593541829,-0.04780944661112799,-0.07990904938106663,7.656115613498331,0.9807178234739568,37.85831285831286,-0.7986021069689708,70.5,3.159522619502108,343.45480506299293,206.07325718307104,,-185.39639134649588,68.58330819283745

wf_3_train,base,2.376246508419244,2.376246508419244,0.37836395691155555,0.6585010817882004,6.715774910564689,1.0922470110840348,38.79074017666768,3.3630405621351995,70.5,3.171906363480642,175.773344116886,105.46412087792362,,-5.401307048498438,351.09350389008176
```

## Failure reasons

```json
{}
```

## Parameter patterns among filter survivors

```json
{
  "trend_length": {
    "most_common_20": {
      "200": 216,
      "100": 216
    },
    "distinct_values": 2,
    "other_configurations": 0
  },
  "slope_lookback": {
    "most_common_20": {
      "5": 432
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "breakout_length": {
    "most_common_20": {
      "50": 216,
      "20": 216
    },
    "distinct_values": 2,
    "other_configurations": 0
  },
  "atr_length": {
    "most_common_20": {
      "14": 216,
      "20": 216
    },
    "distinct_values": 2,
    "other_configurations": 0
  },
  "atr_reference_length": {
    "most_common_20": {
      "50": 432
    },
    "distinct_values": 1,
    "other_configurations": 0
  },
  "atr_expansion_threshold": {
    "most_common_20": {
      "1.0": 216,
      "1.25": 216
    },
    "distinct_values": 2,
    "other_configurations": 0
  },
  "atr_stop_multiplier": {
    "most_common_20": {
      "2.5": 144,
      "1.5": 144,
      "2.0": 144
    },
    "distinct_values": 3,
    "other_configurations": 0
  },
  "reward_risk": {
    "most_common_20": {
      "2.5": 144,
      "2.0": 144,
      "1.5": 144
    },
    "distinct_values": 3,
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
