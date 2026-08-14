# Changelog

## [1.32.0](https://github.com/KasperSkytte/tradezulu/compare/v1.31.3...v1.32.0) (2026-08-14)


### Features

* **agent:** add Dukascopy Bank ([d90226d](https://github.com/KasperSkytte/tradezulu/commit/d90226d35bf920637425a64a2a92b8d8a10d41d7))
* **copier:** one lot limit, a stop the risk modes cannot work without ([8e4c690](https://github.com/KasperSkytte/tradezulu/commit/8e4c690336f9f1dfda4d8594e79c8bf7b2be4217))
* **news:** ForexFactory's stories beside its calendar ([724481e](https://github.com/KasperSkytte/tradezulu/commit/724481efd3c24dd4dafb3d0c00fd8fae65d8c3ad))


### Bug fixes

* **accounts:** stop the slave settings jumping, and group them by question ([da654d3](https://github.com/KasperSkytte/tradezulu/commit/da654d3b575cedc1ebea39fdddb7101ac25ccb63))
* **dashboard:** stop a stray 0 appearing above the cumulative chart ([ca24899](https://github.com/KasperSkytte/tradezulu/commit/ca24899263b81dbf84fea8a165dd9c1cbd2603f8))
* **news:** keep the day bar inside the card's rounded corners ([4bf1c5f](https://github.com/KasperSkytte/tradezulu/commit/4bf1c5f289e28eb391ad74867945b9325e846433))
* **news:** show red, orange and yellow stories by default ([9b7d3f1](https://github.com/KasperSkytte/tradezulu/commit/9b7d3f10cfe01d8e47c385a9af27116ff75dc51b))
* **trades:** drop the Net ROI column when it repeats the P&L column ([b3b5f90](https://github.com/KasperSkytte/tradezulu/commit/b3b5f9088edfc4490f18ceeadf91b1cc87011132))
* **trades:** hide lot sizes along with the money ([10f515f](https://github.com/KasperSkytte/tradezulu/commit/10f515f149cc8e2e156dc5c44458d0916369f666))
* **trades:** say what a trade cost without saying what the account is worth ([8a22517](https://github.com/KasperSkytte/tradezulu/commit/8a225176926dfdcd3400b895008aa048330ba838))


### Documentation

* retake the screenshots ([2bc53df](https://github.com/KasperSkytte/tradezulu/commit/2bc53df00176c8f00a0bfb414becfe9ae34c1ddc))

## [1.31.3](https://github.com/KasperSkytte/tradezulu/compare/v1.31.2...v1.31.3) (2026-08-13)


### Bug fixes

* **accounts:** bring the master back when credentials are entered again ([a29fa75](https://github.com/KasperSkytte/tradezulu/commit/a29fa753fde4a26f4e320d3e81197a49255c83e6))
* **charts:** draw the higher timeframes after the collected one changes ([ffc8801](https://github.com/KasperSkytte/tradezulu/commit/ffc88018cab673c609cfd07a68f3b6d3f8a1276e))

## [1.31.2](https://github.com/KasperSkytte/tradezulu/compare/v1.31.1...v1.31.2) (2026-08-13)


### Bug fixes

* **agent:** build a template for a broker that ships no installer of its own ([37d4640](https://github.com/KasperSkytte/tradezulu/commit/37d46400dcc505063ada8e54e354be199d9d2526))

## [1.31.1](https://github.com/KasperSkytte/tradezulu/compare/v1.31.0...v1.31.1) (2026-08-13)


### Bug fixes

* **dashboard:** call deposits and withdrawals by their names ([43269e3](https://github.com/KasperSkytte/tradezulu/commit/43269e3410df8f38ed6433dae6c701a3367948ca))
* **dashboard:** mark money moved on a day nobody traded ([c746809](https://github.com/KasperSkytte/tradezulu/commit/c746809dd0017a22b66ee0602ac8e296219a81c5))
* **dashboard:** name the funding line after deposits and withdrawals ([762445e](https://github.com/KasperSkytte/tradezulu/commit/762445e2fcc6f625a6640c121dff834e2be56c1d))

## [1.31.0](https://github.com/KasperSkytte/tradezulu/compare/v1.30.0...v1.31.0) (2026-08-13)


### Features

* **dashboard:** mark money in and out on the curve, and total it beside ([3e3b680](https://github.com/KasperSkytte/tradezulu/commit/3e3b6804b8958a22bae4233e4f6912fca1d77955))
* **stats:** measure risk against the equity a trade was opened with ([3ee02b2](https://github.com/KasperSkytte/tradezulu/commit/3ee02b2acf0bea7257d88138213df44fda2dc6be))
* **stats:** report what was paid in and taken out, apart from the trading ([0b3b223](https://github.com/KasperSkytte/tradezulu/commit/0b3b2233ef6f0a271bc6c5556d2b90ff6006270c))


### Bug fixes

* **stats:** count credit when reconstructing what an account was worth ([af997f4](https://github.com/KasperSkytte/tradezulu/commit/af997f43142b68f035e79f8c566651b23af85772))


### Performance

* **copier:** push commands down a held connection, and refuse a stale one ([ab939e4](https://github.com/KasperSkytte/tradezulu/commit/ab939e415817571e206bd047099c8845ee38113f))
* **copier:** report a trade the moment it happens, and poll in milliseconds ([73bbbbf](https://github.com/KasperSkytte/tradezulu/commit/73bbbbf4f0131caeec0cb94edde1bd3cde867f60))
* **copier:** stop making every copy wait ten seconds on the master ([f58c6e6](https://github.com/KasperSkytte/tradezulu/commit/f58c6e68741306596fcb217d69e1e4c4d6762003))
* **mt5:** journal a deal when it happens, not a minute later ([65fbd1c](https://github.com/KasperSkytte/tradezulu/commit/65fbd1c4418fb67eac70c9282a528cebd2e48851))

## [1.30.0](https://github.com/KasperSkytte/tradezulu/compare/v1.29.1...v1.30.0) (2026-08-12)


### Features

* **mt5:** make the expert's own chart a plain background for its status ([7ee9e7f](https://github.com/KasperSkytte/tradezulu/commit/7ee9e7f9e96bb5389751d9fa42d6482aa44f43d4))
* **trades:** a sort control beside the filter, and an order that survives ([609d6d3](https://github.com/KasperSkytte/tradezulu/commit/609d6d39290f4436930f10bc73939127b1b62880))

## [1.29.1](https://github.com/KasperSkytte/tradezulu/compare/v1.29.0...v1.29.1) (2026-08-12)


### Bug fixes

* **chart:** put the fill arrows beside the candles, not on them ([c49a540](https://github.com/KasperSkytte/tradezulu/commit/c49a540e01b693774b2c21df305ae94826703285))
* **demo:** a repeated day stopped the demo journal from seeding at all ([eeabcea](https://github.com/KasperSkytte/tradezulu/commit/eeabcea2aaa0b1ea84550f39a7150ac9cd8ffff4))

## [1.29.0](https://github.com/KasperSkytte/tradezulu/compare/v1.28.0...v1.29.0) (2026-08-12)


### Features

* **accounts:** one live screen, and a banner rather than a dialog ([d6ec67b](https://github.com/KasperSkytte/tradezulu/commit/d6ec67be281c9da65dd0e12339fdfcc48d93d90f))


### Bug fixes

* **agent:** stop a chart piling up on every restart ([5c4afa9](https://github.com/KasperSkytte/tradezulu/commit/5c4afa93842e4de67876cd94a91e53f98ba76b32))
* **filters:** a named period runs to its own end, not to today ([a3147f8](https://github.com/KasperSkytte/tradezulu/commit/a3147f87b53886ee8a08304b8414eebe2fdcb6dc)), closes [#5](https://github.com/KasperSkytte/tradezulu/issues/5)

## [1.28.0](https://github.com/KasperSkytte/tradezulu/compare/v1.27.0...v1.28.0) (2026-08-12)


### Features

* **accounts:** let a viewer take control of a terminal, with the warning first ([e3caf84](https://github.com/KasperSkytte/tradezulu/commit/e3caf84cc3eed39be94703e1ace08bd2a8ad3663))


### Bug fixes

* **accounts:** the terminal viewer drew its screen at zero by zero ([0fa7017](https://github.com/KasperSkytte/tradezulu/commit/0fa701730aa48ed567354ebb95bdff021dbb9480))

## [1.27.0](https://github.com/KasperSkytte/tradezulu/compare/v1.26.2...v1.27.0) (2026-08-12)


### Features

* **accounts:** watch and restart a terminal from the account it belongs to ([1a3cc6d](https://github.com/KasperSkytte/tradezulu/commit/1a3cc6d5129ed9167141edf7421d57be8375b0be))
* **agent:** a screen of its own for every terminal, served over VNC ([9e1cfd0](https://github.com/KasperSkytte/tradezulu/commit/9e1cfd06f062c1a02fea66a01549294da9f1c68a))
* **copier:** refuse a stop too tight to survive another broker's prices ([2043d66](https://github.com/KasperSkytte/tradezulu/commit/2043d6688c8c21597b2d5d5362ce3ec02d4cc31c))


### Bug fixes

* **agent:** move a terminal to its own screen after an upgrade ([97ac308](https://github.com/KasperSkytte/tradezulu/commit/97ac3080843c733500d2af9a8fcb429d714328a3))
* **copier:** a terminal with no session must not read as a wiped account ([813e710](https://github.com/KasperSkytte/tradezulu/commit/813e71009c846752c092f5c31ef097182703ab5d))


### Documentation

* what an upgrade to per-terminal screens does to a running server ([8daa60f](https://github.com/KasperSkytte/tradezulu/commit/8daa60f6c34a735b9a43e3337f05c0c61afeedc3))


### Build & packaging

* **install:** install x11vnc, and clear every display on the way out ([1920928](https://github.com/KasperSkytte/tradezulu/commit/19209289ebe7e06e96d5fa32b97474769f5f39b5))

## [1.26.2](https://github.com/KasperSkytte/tradezulu/compare/v1.26.1...v1.26.2) (2026-08-11)


### Bug fixes

* **dashboard:** six stat tiles do not fit a 1440 screen ([1820e83](https://github.com/KasperSkytte/tradezulu/commit/1820e830e7f4cc24abe4c0ee6fe8915cdd77037d))
* **reports:** a readable ruler on the box plots in money ([59d6b72](https://github.com/KasperSkytte/tradezulu/commit/59d6b72e793ae9b843a79d401c7cb4ce77581543))


### Documentation

* order the screenshots by the menu, and add the news calendars ([ccf26b8](https://github.com/KasperSkytte/tradezulu/commit/ccf26b8b67652e9f9dbe30c456ae024080b58f0e))
* retake the screenshots ([fe6ea17](https://github.com/KasperSkytte/tradezulu/commit/fe6ea17e2df129e6483dc713d52b4e99a013d819))

## [1.26.1](https://github.com/KasperSkytte/tradezulu/compare/v1.26.0...v1.26.1) (2026-08-10)


### Bug fixes

* **reports:** a ruler on axes narrower than a single R ([7cafe93](https://github.com/KasperSkytte/tradezulu/commit/7cafe93679705c5b2de91e7d885b2cd1ff5ef018))
* **reports:** draw a series of fewer than four trades instead of dropping it ([a06ef00](https://github.com/KasperSkytte/tradezulu/commit/a06ef00dec71be788d743614989642f4ebe814f6))

## [1.26.0](https://github.com/KasperSkytte/tradezulu/compare/v1.25.2...v1.26.0) (2026-08-10)


### Features

* **agent:** let a viewer drive the terminals, with watch --control ([da75e22](https://github.com/KasperSkytte/tradezulu/commit/da75e2246ad3f5ea296598495119bb03b6a0c5b0))


### Bug fixes

* **agent:** show the terminal that was asked for, not the one on top ([d3753cb](https://github.com/KasperSkytte/tradezulu/commit/d3753cb22fe9935d39d269710fd8a1f23ba8eaeb))
* **reports:** label the zero gridline zero, not -0.00 ([308920b](https://github.com/KasperSkytte/tradezulu/commit/308920b50b1fdafc58a50535a907e26b75fac379))
* **reports:** put planned and realised on one axis ([10a9b80](https://github.com/KasperSkytte/tradezulu/commit/10a9b80d1609b169807ac63befb197de8d161f5d))

## [1.25.2](https://github.com/KasperSkytte/tradezulu/compare/v1.25.1...v1.25.2) (2026-08-07)


### Bug fixes

* **copier:** clearing a halt moves the day's baseline with it ([86df7ea](https://github.com/KasperSkytte/tradezulu/commit/86df7ead6955a73af63d554e8059d40af0b2242e))
* **copier:** refuse a trade whose size cannot be checked against the cap ([76a7304](https://github.com/KasperSkytte/tradezulu/commit/76a73040f5a913690712ca16df3f07a666bc272a))
* **copier:** the terminal reports every symbol, not just Market Watch ([bd5a0f1](https://github.com/KasperSkytte/tradezulu/commit/bd5a0f1c11faa8afde317a5e7e965ae4d0501667))

## [1.25.1](https://github.com/KasperSkytte/tradezulu/compare/v1.25.0...v1.25.1) (2026-08-07)


### Bug fixes

* **filters:** the period and account survive changing page ([a475d41](https://github.com/KasperSkytte/tradezulu/commit/a475d41c8e33eef10f40b6a76ca887a69c0d37bd))

## [1.25.0](https://github.com/KasperSkytte/tradezulu/compare/v1.24.0...v1.25.0) (2026-08-06)


### Features

* **calendar:** show what a week made as a percentage ([372ca7a](https://github.com/KasperSkytte/tradezulu/commit/372ca7a0d22edb9924b72eb6d60244a092e9d469))
* **journal:** tag a loss that ran past its stop ([c8a652f](https://github.com/KasperSkytte/tradezulu/commit/c8a652fb2df24046d353fd5713044d735dd2ba3b))
* **journal:** tag a trade that went on without a stop ([c720c5e](https://github.com/KasperSkytte/tradezulu/commit/c720c5ec0037196bab37e8db8e9754ee8ffede42))
* **reports:** box plots of what was planned against what came back ([3ea48ae](https://github.com/KasperSkytte/tradezulu/commit/3ea48aee7a668d9c25d0557013e8ac8907bf99d8))
* **reports:** the box plots answer in whichever unit is selected ([568f557](https://github.com/KasperSkytte/tradezulu/commit/568f5577e852dea0a8c901ac186ade3f584d2501))
* **settings:** choose whether typical figures are the median or the mean ([dc3824b](https://github.com/KasperSkytte/tradezulu/commit/dc3824b4060464b2285bc0fcc45a38f6deda0dfd))
* **stats:** show how often losses ran past the stop ([3227cae](https://github.com/KasperSkytte/tradezulu/commit/3227cae840d4caa00bc6292269e68a5ae84d8322))
* **stats:** the win rate this payoff needs to break even ([7830701](https://github.com/KasperSkytte/tradezulu/commit/7830701721f98ea4d2e64e86a96f9990b789763d))


### Bug fixes

* **agent:** a terminal that is not logged in must not erase the balance ([2b05af3](https://github.com/KasperSkytte/tradezulu/commit/2b05af3cddccaae288d3ae573b3aeb97fb3cf2da))
* **stats:** a typical risk figure that one bad stop cannot decide ([dc1b28f](https://github.com/KasperSkytte/tradezulu/commit/dc1b28fa747baf394b15ea9d341d1da78c3acc27))


### Documentation

* **dashboard:** say what the risk rows are measuring ([f6076e2](https://github.com/KasperSkytte/tradezulu/commit/f6076e26fc5102401bfed4c1168f60b2ac6d723f))

## [1.24.0](https://github.com/KasperSkytte/tradezulu/compare/v1.23.2...v1.24.0) (2026-08-06)


### Features

* **chart:** the high/low labels can be switched off, from the chart ([06cd0a3](https://github.com/KasperSkytte/tradezulu/commit/06cd0a31b9aa94c967e42016a84557431ad43c69))


### Bug fixes

* **chart:** no current-price line on the Studio chart ([9ca20f5](https://github.com/KasperSkytte/tradezulu/commit/9ca20f5edb8f192e8ca5d04e75d7a25b493a40ed))


### Refactoring

* **chart:** one stored-candle chart, named after what draws it ([96e6131](https://github.com/KasperSkytte/tradezulu/commit/96e613132cfd3e7241774ee8fcff3a233ba9c742))

## [1.23.2](https://github.com/KasperSkytte/tradezulu/compare/v1.23.1...v1.23.2) (2026-08-06)


### Bug fixes

* **calendar:** scope it to the selected account like everything else ([8d46e46](https://github.com/KasperSkytte/tradezulu/commit/8d46e46042b55ab208176512299d2fefc9c570f2))

## [1.23.1](https://github.com/KasperSkytte/tradezulu/compare/v1.23.0...v1.23.1) (2026-08-05)


### Bug fixes

* **calendar:** file a trade on the day it happened ([a04a867](https://github.com/KasperSkytte/tradezulu/commit/a04a867c76b1d0b577a9d663e6d14be5b2303e93))

## [1.23.0](https://github.com/KasperSkytte/tradezulu/compare/v1.22.0...v1.23.0) (2026-08-05)


### Features

* **accounts:** pick a slave's broker and trade server, not type them ([4e9dfc7](https://github.com/KasperSkytte/tradezulu/commit/4e9dfc764bda3b9443cbf8b524fc0e269320131f))
* **agent:** say whether a terminal actually started ([06c4634](https://github.com/KasperSkytte/tradezulu/commit/06c463428792cc1e30a90a85c96827e3235a4bc0))
* **charts:** choose which timeframe the terminal collects, so M1 is possible ([d71e106](https://github.com/KasperSkytte/tradezulu/commit/d71e1068e4f7025633b2935eb6905fd3279e589b))


### Bug fixes

* **settings:** offer Studio as a default chart, and W1 as a timeframe ([3338ca6](https://github.com/KasperSkytte/tradezulu/commit/3338ca6289e5763401b563d96ed73c1d70b082a9))

## [1.22.0](https://github.com/KasperSkytte/tradezulu/compare/v1.21.0...v1.22.0) (2026-08-05)


### Features

* **charts:** set the history window in days, and how much opens on screen ([a9d60ac](https://github.com/KasperSkytte/tradezulu/commit/a9d60ac0139c468ced25ff9f5dce1afd7a0fed13))

## [1.21.0](https://github.com/KasperSkytte/tradezulu/compare/v1.20.1...v1.21.0) (2026-08-05)


### Features

* **chart:** a Studio tab that draws the position on the candles ([0c9eba4](https://github.com/KasperSkytte/tradezulu/commit/0c9eba40d4c44c20e4f20d35398ab25d6d8f2960))
* **chart:** read a trade in your own timezone, optionally ([c98a59d](https://github.com/KasperSkytte/tradezulu/commit/c98a59dc121b0c88999bb75dac24dcb8be33f0d4))
* **copier:** show and correct the symbols a slave was matched to ([f5a3239](https://github.com/KasperSkytte/tradezulu/commit/f5a323909b6d830c221f1a03697de7cb99dafdf0))
* **settings:** the clock choice applies to every time in the journal ([4a84db7](https://github.com/KasperSkytte/tradezulu/commit/4a84db7ecedba517554fdd521242ad5a8ada6cdc))


### Bug fixes

* **accounts:** the broker's clock offset reaches the browser ([53f58bf](https://github.com/KasperSkytte/tradezulu/commit/53f58bf37f00e8586c5e64aa91abc62c34e092f5))
* **api:** stop a healthy terminal reporting itself as "quiet 2 hours ago" ([00ed805](https://github.com/KasperSkytte/tradezulu/commit/00ed8053830eb64da4c90ced80ba0cc0699a35b5))
* **chart:** put the fills and the candles on one clock ([2df97fd](https://github.com/KasperSkytte/tradezulu/commit/2df97fd5bcc7d4a078225ab2e3aed63e180d6a67))
* **copier:** match the instrument when the master is the decorated one ([9660ffe](https://github.com/KasperSkytte/tradezulu/commit/9660ffe1c1bb281d3deb6adb9434ebbee1ece43f))

## [1.20.1](https://github.com/KasperSkytte/tradezulu/compare/v1.20.0...v1.20.1) (2026-08-04)


### Bug fixes

* **reports:** the hour buckets follow the clock setting too ([f37bef5](https://github.com/KasperSkytte/tradezulu/commit/f37bef5c7cc544f75651ba1d6211e5747771b5e1))

## [1.20.0](https://github.com/KasperSkytte/tradezulu/compare/v1.19.0...v1.20.0) (2026-08-04)


### Features

* **settings:** choose between a 24-hour and a 12-hour clock ([3b61095](https://github.com/KasperSkytte/tradezulu/commit/3b610955387ed3a12c819d16dec0a3fa631d2855))


### Bug fixes

* **reports:** read setups from the tags as well as the field ([0331f5e](https://github.com/KasperSkytte/tradezulu/commit/0331f5e51e9ea330229dc8b3095416c16c30aaf8))

## [1.19.0](https://github.com/KasperSkytte/tradezulu/compare/v1.18.0...v1.19.0) (2026-08-04)


### Features

* **dashboard:** show the balance when amounts are on ([4ff435f](https://github.com/KasperSkytte/tradezulu/commit/4ff435fef663a44879c6d7589bc6b4817b737f1b))


### Bug fixes

* **charts:** widen the TradingView window until the trade is in it ([b4d9de9](https://github.com/KasperSkytte/tradezulu/commit/b4d9de97b4d12eaf3af2eac21f3dfed69ac86d65))
* **stats:** the newest trades had no Net ROI ([a0ba5d1](https://github.com/KasperSkytte/tradezulu/commit/a0ba5d15e8dba4c5d944c80554ca030d33f8407d))


### Refactoring

* **ui:** put accounts back under settings ([17da78b](https://github.com/KasperSkytte/tradezulu/commit/17da78bb74ab1f97f1d321620fae3c61ff8d4a28))

## [1.18.0](https://github.com/KasperSkytte/tradezulu/compare/v1.17.0...v1.18.0) (2026-08-04)


### Features

* **dashboard:** let a figure about one trade open that trade ([91e9958](https://github.com/KasperSkytte/tradezulu/commit/91e99589031214bf785c4221242dbf9cfef3aae1))

## [1.17.0](https://github.com/KasperSkytte/tradezulu/compare/v1.16.0...v1.17.0) (2026-08-04)


### Features

* **news:** make ForexFactory the default, and give it a filter worth using ([36cfd6f](https://github.com/KasperSkytte/tradezulu/commit/36cfd6f8fab456297628c8be07ac2f64cba74fa6))


### Bug fixes

* **settings:** say that a breakeven threshold of 0 switches it off ([e60eda3](https://github.com/KasperSkytte/tradezulu/commit/e60eda3beeabfe9f271207d83f6e502d2b50f034))


### Refactoring

* **news:** controls first, the warning last ([53d0848](https://github.com/KasperSkytte/tradezulu/commit/53d08489382c4a513273111a1de5692ba2ff1638))


### Documentation

* **settings:** explain what "Even losses" actually measures ([4c0bfed](https://github.com/KasperSkytte/tradezulu/commit/4c0bfedcde01cdf3de689625799bc6c7f0f9dc01))

## [1.16.0](https://github.com/KasperSkytte/tradezulu/compare/v1.15.2...v1.16.0) (2026-08-04)


### Features

* **news:** add ForexFactory beside TradingView, and remember the choice ([1bb06bc](https://github.com/KasperSkytte/tradezulu/commit/1bb06bc2bfa62b4e38edfa09fbe0eefbd407a9a2))


### Documentation

* the news calendar has two sources now ([22ca7c2](https://github.com/KasperSkytte/tradezulu/commit/22ca7c2874d1811645f2a689036c37e8bc448228))

## [1.15.2](https://github.com/KasperSkytte/tradezulu/compare/v1.15.1...v1.15.2) (2026-08-04)


### Bug fixes

* **reports:** the axes have to hide money too ([3aac2d6](https://github.com/KasperSkytte/tradezulu/commit/3aac2d6a9c4a4cff227e8066a0c6bea9a6de430f))

## [1.15.1](https://github.com/KasperSkytte/tradezulu/compare/v1.15.0...v1.15.1) (2026-08-03)


### Documentation

* retake the screenshots on an account that is going somewhere ([45f20c9](https://github.com/KasperSkytte/tradezulu/commit/45f20c9a7cb722fce890038cabfc96beb9f88314))

## [1.15.0](https://github.com/KasperSkytte/tradezulu/compare/v1.14.2...v1.15.0) (2026-08-03)


### Features

* **charts:** collect M5 and build every longer timeframe from it ([494fe80](https://github.com/KasperSkytte/tradezulu/commit/494fe808f09413e819ebb41d30000737c921bef0))


### Documentation

* features ([576c2a1](https://github.com/KasperSkytte/tradezulu/commit/576c2a1478cff58b3a5a3d81696a1e3cb88130e1))
* say plainly that attaching an account is GUI automation ([3405a1d](https://github.com/KasperSkytte/tradezulu/commit/3405a1d9c35e7ed1cd4fca19ecf548730ab5911d))
* shorten the feature list, journal first ([6513e7a](https://github.com/KasperSkytte/tradezulu/commit/6513e7ad4ccb84735ab7218332fba79490262693))

## [1.14.2](https://github.com/KasperSkytte/tradezulu/compare/v1.14.1...v1.14.2) (2026-08-03)


### Bug fixes

* **ui:** make archived accounts removable ([8f98efe](https://github.com/KasperSkytte/tradezulu/commit/8f98efeff83c822ad85b0868c81be3318108ec04))


### Refactoring

* **ui:** move manual import to the accounts page ([8412537](https://github.com/KasperSkytte/tradezulu/commit/8412537c58a9f6b144310f53cc16fc3a7414c3d1))

## [1.14.1](https://github.com/KasperSkytte/tradezulu/compare/v1.14.0...v1.14.1) (2026-08-03)


### Bug fixes

* **accounts:** stop creating second masters, and let one be removed ([e56a056](https://github.com/KasperSkytte/tradezulu/commit/e56a056da63a36d84439279b39477f2cc5ad5436))
* **agent:** never run two terminals for one account, and say what is running ([9c3ffa4](https://github.com/KasperSkytte/tradezulu/commit/9c3ffa4930fdc27fbe06cd8ced5060303e764797))
* **ci:** lint every shell script, at a version that does not move ([a2623f9](https://github.com/KasperSkytte/tradezulu/commit/a2623f9afd9f7bfd91d9a41e40ba05a36c71437e))
* **reports:** honour the amounts setting here too ([cf2e3e1](https://github.com/KasperSkytte/tradezulu/commit/cf2e3e1f2d64d00323c7f0b64707dce3bfed41ad))


### Refactoring

* **ui:** put forgetting and terminal status on the account they describe ([5dace4d](https://github.com/KasperSkytte/tradezulu/commit/5dace4d0c0722e0f0b7333813d3bb6da25bbd2a6))

## [1.14.0](https://github.com/KasperSkytte/tradezulu/compare/v1.13.1...v1.14.0) (2026-08-03)


### Features

* **score:** put drawdown back, and let every component be switched off ([735db68](https://github.com/KasperSkytte/tradezulu/commit/735db68ddc9bb6053c7ada9f584daa73c39b9418))


### Bug fixes

* **stats:** work out balances backwards from what the account is worth ([47a1294](https://github.com/KasperSkytte/tradezulu/commit/47a12949bc55f77215d835e0bdedf0ee2611e936))


### Refactoring

* **settings:** name the amounts toggle after what it does ([65c4268](https://github.com/KasperSkytte/tradezulu/commit/65c42684fc0aa982559fbb01c3cf0fa79261f364))

## [1.13.1](https://github.com/KasperSkytte/tradezulu/compare/v1.13.0...v1.13.1) (2026-08-03)


### Bug fixes

* **agent:** recover a terminal that starts but never works ([4a4d264](https://github.com/KasperSkytte/tradezulu/commit/4a4d2643751a05a7bfff66829f371ee3757046c4))
* **agent:** say which accounts still exist, not just which want a terminal ([e5a4d95](https://github.com/KasperSkytte/tradezulu/commit/e5a4d95e851e5887e44452d0aac186626113186c))
* **install:** check for the commands the terminals need, not dpkg's word ([426a14a](https://github.com/KasperSkytte/tradezulu/commit/426a14a9d8106732c0ee9d9d15962be6dd7c3ccd))
* **uninstall:** remove what was actually left behind ([f51826b](https://github.com/KasperSkytte/tradezulu/commit/f51826b8cbbb6991a8dd0c7fd64a858ecdc53783))


### Performance

* **agent:** compile the Expert Advisor once, not once per account ([a307387](https://github.com/KasperSkytte/tradezulu/commit/a307387b1ed342d2eb1baf45952a5a4fc03a667a))


### Refactoring

* **ui:** give the economic calendar its own page ([04d7a78](https://github.com/KasperSkytte/tradezulu/commit/04d7a784d78d6ad311980ce68a7063e50763cd5e))

## [1.13.0](https://github.com/KasperSkytte/tradezulu/compare/v1.12.0...v1.13.0) (2026-08-02)


### Features

* **dashboard:** add an economic calendar, high-impact dollar news by default ([3a0cded](https://github.com/KasperSkytte/tradezulu/commit/3a0cded947d9045a99ae70d6d2e29ea7f0ffcae9))

## [1.12.0](https://github.com/KasperSkytte/tradezulu/compare/v1.11.0...v1.12.0) (2026-08-02)


### Features

* **agent:** set the weekly restart window from the web interface ([7a779aa](https://github.com/KasperSkytte/tradezulu/commit/7a779aa6a0efe5593eb6a5ead11467072b8cfc1f))
* **charts:** work the TradingView exchange prefix out from the broker ([8cb49ba](https://github.com/KasperSkytte/tradezulu/commit/8cb49ba39714bfe644a540daba0c8b8ac2c5ba54))
* **dashboard:** show percentages rather than money by default ([1790d1b](https://github.com/KasperSkytte/tradezulu/commit/1790d1b59a1d235bba89f01b3f755ebbc1bde422))
* **export:** give exporting its own card, covering every account ([0e41785](https://github.com/KasperSkytte/tradezulu/commit/0e41785d9ff40f446c609335f430cdf5dc3252fb))
* **metrics:** replace drawdown with how even the losses were ([8a72eb2](https://github.com/KasperSkytte/tradezulu/commit/8a72eb2627d0e1164495ec454b70c8705b4a16e3))
* **risk:** stop inventing risk for trades that never had a stop ([b5bf762](https://github.com/KasperSkytte/tradezulu/commit/b5bf762592175a1c36e0609691ad8191920fa7b6))
* **tags:** make the tag groups adjustable ([e191812](https://github.com/KasperSkytte/tradezulu/commit/e191812b91d67f0dfad38af0923dd2314e48ad1d))


### Bug fixes

* **agent:** measure the Options dialog instead of guessing where it is ([fd9e815](https://github.com/KasperSkytte/tradezulu/commit/fd9e815ae448f0803e2c22941b4ef8e20264bc91))
* **import:** read MetaTrader reports by layout, and accept the spreadsheet ([1885d77](https://github.com/KasperSkytte/tradezulu/commit/1885d77f32c61ee56ce51ab82dcb07b960adb3bf))


### Refactoring

* **ui:** put MetaTrader with the accounts it feeds ([423e3af](https://github.com/KasperSkytte/tradezulu/commit/423e3af700822e75bf9394dc92a5d2697b3f80e4))

## [1.11.0](https://github.com/KasperSkytte/tradezulu/compare/v1.10.0...v1.11.0) (2026-07-31)


### Features

* **agent:** add a script for looking at the terminals ([3b9e173](https://github.com/KasperSkytte/tradezulu/commit/3b9e173619ff06a863de5853b9b9208f5ddf3e06))


### Bug fixes

* **agent:** add the missing re import ([87d7f71](https://github.com/KasperSkytte/tradezulu/commit/87d7f714b13fedf84f1db76c03868b172b54a393))
* **mt5:** require a password when the stored account is changed ([a3a1572](https://github.com/KasperSkytte/tradezulu/commit/a3a157244fee0634f6d76c7d11ae2b993a871829))

## [1.10.0](https://github.com/KasperSkytte/tradezulu/compare/v1.9.2...v1.10.0) (2026-07-31)


### Features

* **agent:** bring an archived account back as master when its credentials return ([cff24c5](https://github.com/KasperSkytte/tradezulu/commit/cff24c5b68ad53d509580979c34672e17d87f53e))


### Bug fixes

* **uninstall:** tear the whole compose stack down, not only what the file still lists ([31b93a6](https://github.com/KasperSkytte/tradezulu/commit/31b93a6382a6c535f507dac1dd689b2ccfbf874b))

## [1.9.2](https://github.com/KasperSkytte/tradezulu/compare/v1.9.1...v1.9.2) (2026-07-31)


### Bug fixes

* **accounts:** make forgetting an account delete its history ([2970594](https://github.com/KasperSkytte/tradezulu/commit/2970594fbbe8fbef00732a70ea2ef2c8c776248b))
* **agent:** give a new master account its own row instead of the old one's ([7f8ff3f](https://github.com/KasperSkytte/tradezulu/commit/7f8ff3f3b0e876b4935f1418cf8bd8ea6636cf9d))
* **stats:** scope the equity series to one account and rebase it to the window ([85b23b6](https://github.com/KasperSkytte/tradezulu/commit/85b23b6636dde2fe61cbb07df27ee04653c7611e))

## [1.9.1](https://github.com/KasperSkytte/tradezulu/compare/v1.9.0...v1.9.1) (2026-07-31)


### Bug fixes

* **copier:** make the minimum-lot setting actually rescue a small size ([449b91d](https://github.com/KasperSkytte/tradezulu/commit/449b91d5fe3c624b9c3dcbb490a8cde825f1de7e)), closes [#20](https://github.com/KasperSkytte/tradezulu/issues/20)
* **stats:** scope the journal to one account, and withhold what several cannot mean ([7e79af1](https://github.com/KasperSkytte/tradezulu/commit/7e79af12dc6da5f52969e9612fedab1060e27bd9))

## [1.9.0](https://github.com/KasperSkytte/tradezulu/compare/v1.8.2...v1.9.0) (2026-07-31)


### Features

* **copier:** size by a percentage of balance, and drop the extra scaling factor ([d0fb2cc](https://github.com/KasperSkytte/tradezulu/commit/d0fb2cc9616b1bd7bb5c2e17d1d3c4e439776699))
* **copier:** work the broker's symbol naming out from its own symbol list ([79f2741](https://github.com/KasperSkytte/tradezulu/commit/79f274130b1ded6a955fd843880075c4f93d3863))


### Refactoring

* **ui:** move the installation facts out of the MetaTrader settings ([35aa60b](https://github.com/KasperSkytte/tradezulu/commit/35aa60be2fae5c6812a60a40968b41bf93b6df4d))
* **ui:** rework the slave account settings ([4f4d7b2](https://github.com/KasperSkytte/tradezulu/commit/4f4d7b2c376c09b361b6d8a5b5552699c81465c3))


### Documentation

* move all but the dashboard screenshot to a page of its own ([f825d6e](https://github.com/KasperSkytte/tradezulu/commit/f825d6ead1949a16f919a204cbeff476aeac793d))
* refresh the screenshots ([3e24caf](https://github.com/KasperSkytte/tradezulu/commit/3e24caf4803b5ad8b84271359dd7b0552f899385))

## [1.8.2](https://github.com/KasperSkytte/tradezulu/compare/v1.8.1...v1.8.2) (2026-07-31)


### Bug fixes

* **copier:** count the account's real positions in the exposure limits ([11297c5](https://github.com/KasperSkytte/tradezulu/commit/11297c5375f2db80fded4c4038ff5807e3efcf66))
* **copier:** read banked profit for the daily target and consistency cap ([03a1b23](https://github.com/KasperSkytte/tradezulu/commit/03a1b2365634dda1638da186c32fd0a45621897a))
* **pwa:** reload the page when a new service worker takes over ([fd21315](https://github.com/KasperSkytte/tradezulu/commit/fd21315e4d903163ab2c795c6a5b4181fd64add5))
* **ui:** put the toggle knob back inside its track ([c01a62d](https://github.com/KasperSkytte/tradezulu/commit/c01a62d0f2c1f266512ab5850e40fabe3e556956))


### Refactoring

* **ui:** drop the version from the sidebar ([32a9d40](https://github.com/KasperSkytte/tradezulu/commit/32a9d40476b787c633fb21d691ff372311786e24))

## [1.8.1](https://github.com/KasperSkytte/tradezulu/compare/v1.8.0...v1.8.1) (2026-07-31)


### Bug fixes

* **agent:** start a terminal for every account that has credentials ([eabdda2](https://github.com/KasperSkytte/tradezulu/commit/eabdda2be56f9535e2115efacdb6d3093a86b6d4))
* **copier:** close dry-run links when a slave is taken live ([d746b73](https://github.com/KasperSkytte/tradezulu/commit/d746b737c900861d398afde86fb1a6081cb25f21))
* **copier:** record a standing skip once instead of on every poll ([24ea036](https://github.com/KasperSkytte/tradezulu/commit/24ea03616d591cfef3666c03d1042183c765e1d1))
* **copier:** reuse a master position's link instead of skipping when one exists ([249a354](https://github.com/KasperSkytte/tradezulu/commit/249a354a908ae8093c005faf84951a8b4bbc388e))


### Documentation

* drop the untested-copier caveat now that it has been run live ([8991f67](https://github.com/KasperSkytte/tradezulu/commit/8991f67a0f1d03cd0951654d72c026a48bb90bea)), closes [#10](https://github.com/KasperSkytte/tradezulu/issues/10)

## [1.8.0](https://github.com/KasperSkytte/tradezulu/compare/v1.7.0...v1.8.0) (2026-07-31)


### Features

* **stats:** measure a period against the balance it opened with ([9f92e82](https://github.com/KasperSkytte/tradezulu/commit/9f92e82542a4132e33088fb18f3b60353acf8c04))


### Bug fixes

* **calendar:** show the day's return, not its win rate ([d8bbb3b](https://github.com/KasperSkytte/tradezulu/commit/d8bbb3bf4557c88d931a9c378f0742bac26d2b86))
* **ui:** stop the page panning sideways on a phone ([842f15d](https://github.com/KasperSkytte/tradezulu/commit/842f15d00c0392338fef0e656a2c574756c8388a))


### Documentation

* refresh the screenshots and correct what they showed ([67dda38](https://github.com/KasperSkytte/tradezulu/commit/67dda38b4cd1ba8273282046cbca848409aa0e2a))

## [1.7.0](https://github.com/KasperSkytte/tradezulu/compare/v1.6.0...v1.7.0) (2026-07-31)


### Features

* **calendar:** show each day as a percentage of the account ([765e91e](https://github.com/KasperSkytte/tradezulu/commit/765e91ed67912dbd4a16a6faa187f8769631ecfa))
* **reports:** read a breakdown in money, R, or percent of the account ([f7380e5](https://github.com/KasperSkytte/tradezulu/commit/f7380e5e04982cda5d542ee00a8e2643acb6f9a7))
* **settings:** drop the configurable account size ([21b46f4](https://github.com/KasperSkytte/tradezulu/commit/21b46f40f65b88a7dc7ba6d595a3be54d529c5d0))
* **trades:** show each trade as a share of the balance it risked ([4448c31](https://github.com/KasperSkytte/tradezulu/commit/4448c31bc993a931f8af5ecd9866c8373e943ed5))


### Bug fixes

* **calendar:** measure a day against that morning's balance ([dd3fe9c](https://github.com/KasperSkytte/tradezulu/commit/dd3fe9c47de5a916fee2b3b97291779c3933083f))

## [1.6.0](https://github.com/KasperSkytte/tradezulu/compare/v1.5.0...v1.6.0) (2026-07-31)


### Features

* **mt5:** upload candles, so every trade has a chart to draw ([5c90f38](https://github.com/KasperSkytte/tradezulu/commit/5c90f382317fc000561fcd88a4b88deb7dfea5dc))
* **stats:** draw equity beside balance, and fix invisible popovers ([44031f7](https://github.com/KasperSkytte/tradezulu/commit/44031f78618e7673b68538bc93e88fa6632fa62e))

## [1.5.0](https://github.com/KasperSkytte/tradezulu/compare/v1.4.0...v1.5.0) (2026-07-31)


### Features

* **mt5:** pick a broker and its server, and say when a terminal is starting ([e79a545](https://github.com/KasperSkytte/tradezulu/commit/e79a545fbca87e40cb80e533f1e775b8c7f39480))
* **mt5:** real server lists, from the terminal's own search ([57165f9](https://github.com/KasperSkytte/tradezulu/commit/57165f97a02f1200902559fc13b8d84faeba517a))
* **stats:** breakeven by percent of account, and W/L/BE on the curve ([5ff8b15](https://github.com/KasperSkytte/tradezulu/commit/5ff8b15ce0df5d09174dedaeed8068db964c7f71))
* **trades:** tag a batch with several tags at once, grouped by kind ([b9b995a](https://github.com/KasperSkytte/tradezulu/commit/b9b995a492f864eda0e7d3fb0f6cf6ea2028fa19))
* **ui:** explain the jargon, and give breakevens their own colour ([457ead6](https://github.com/KasperSkytte/tradezulu/commit/457ead64558fa43ddb59506f734ba4662184354f))


### Bug fixes

* **install:** drop privilege correctly when already root ([afdc4f2](https://github.com/KasperSkytte/tradezulu/commit/afdc4f27fe5395726bbef74601742ca7777c6497))

## [1.4.0](https://github.com/KasperSkytte/tradezulu/compare/v1.3.0...v1.4.0) (2026-07-31)


### Features

* **install:** add an uninstaller that cannot delete the wrong thing ([f6042c7](https://github.com/KasperSkytte/tradezulu/commit/f6042c7ff89317788d31ae7269b8513ed60f0a85))
* **install:** let a service account own and run the terminals ([d41b25a](https://github.com/KasperSkytte/tradezulu/commit/d41b25ac26c834540dbe23af18334fb198e3eebf))


### Bug fixes

* **install:** find the Wine build by pattern, and let the user read it ([561c4f1](https://github.com/KasperSkytte/tradezulu/commit/561c4f12b06c8754cb4f09f5bad48d3925888f4c))
* **install:** give the agent a runtime directory of its own ([5436b75](https://github.com/KasperSkytte/tradezulu/commit/5436b75394de4df3138f98fb0598cbd21e4ed42b))
* **install:** install the agent as a system service ([2b12251](https://github.com/KasperSkytte/tradezulu/commit/2b122510e73368971f5f5f315a39445595bc903a))

## [1.3.0](https://github.com/KasperSkytte/tradezulu/compare/v1.2.1...v1.3.0) (2026-07-31)


### Features

* **agent:** let the master terminal claim its own account row ([8c95c3a](https://github.com/KasperSkytte/tradezulu/commit/8c95c3acf48ee018188ad088dd39d1618cd3642a))
* **agent:** provision a terminal per account without anyone configuring it ([b5d3b9b](https://github.com/KasperSkytte/tradezulu/commit/b5d3b9b9789754a58a43a34d78bce8afc3f875da))
* **agent:** restart terminals weekly, and drop the containerised bridge ([b02f351](https://github.com/KasperSkytte/tradezulu/commit/b02f3513cb5a38961a99b1de24daee666a548e39))
* **copier:** drive the terminals with an Expert Advisor, not the Python API ([5eaf27b](https://github.com/KasperSkytte/tradezulu/commit/5eaf27bbf313edfdf3ad789e12dc437d1c381297))
* **install:** set up a server from one script, terminals included ([c5db917](https://github.com/KasperSkytte/tradezulu/commit/c5db917c946cd2b3c7c367c59819f9260c42f130))
* **mt5:** send closed deals, so the journal fills itself ([9ff0597](https://github.com/KasperSkytte/tradezulu/commit/9ff0597f942d41edd6d0051f8d3ee3aad19d519e))


### Bug fixes

* **agent:** make a provisioned terminal actually run its expert ([e4b0f4d](https://github.com/KasperSkytte/tradezulu/commit/e4b0f4d22cac841b6e30ae8872265acb37264f5a))
* **mt5-bridge:** prefer IPv4, and ship the tools needed to see the terminal ([b5c368b](https://github.com/KasperSkytte/tradezulu/commit/b5c368b1fc2021a60a2cfa22bf6ed352db70df43))


### Documentation

* correct the WoW64 theory -- the installer is 64-bit ([2e6831d](https://github.com/KasperSkytte/tradezulu/commit/2e6831dfaa7fe7a8650e09604f9b2138aba4bb91))
* MetaQuotes' own Linux recipe, and where following it stops ([d0e378f](https://github.com/KasperSkytte/tradezulu/commit/d0e378f7e64ccff827fb3b222ea5559ca256e36f))
* native winhttp/wininet do not help either ([1b66c53](https://github.com/KasperSkytte/tradezulu/commit/1b66c53c502662b3da146f0151df5ee47ca916d0))
* point at the issue tracker, and name the three that matter ([cb88960](https://github.com/KasperSkytte/tradezulu/commit/cb88960db2ca9645f1a7f93361de07e1bd63dfc9))
* the GUI works and the login dialog was the blocker; the network is not ([c5f540b](https://github.com/KasperSkytte/tradezulu/commit/c5f540b276723928234be29f711f3779ddbf8816))
* the staging image has no WoW64, which is why the recipe cannot finish ([6177cd1](https://github.com/KasperSkytte/tradezulu/commit/6177cd1eca34253c99079f3a1d5bb54b6255b4e2))
* the terminal never authorises, so the EA route is closed too ([af05d5e](https://github.com/KasperSkytte/tradezulu/commit/af05d5e8251d6313138eda56f12653c7f9502965))

## [1.2.1](https://github.com/KasperSkytte/tradezulu/compare/v1.2.0...v1.2.1) (2026-07-29)


### Documentation

* mt5linux tested end to end, and it does not fix this ([ad096d2](https://github.com/KasperSkytte/tradezulu/commit/ad096d273293d5cf5f4c8f60fbcdda215e95016f))
* the terminal never serves the API, and non-root is required ([b1b125c](https://github.com/KasperSkytte/tradezulu/commit/b1b125c52740f417975cda39f08fd583c3986de0))

## [1.2.0](https://github.com/KasperSkytte/tradezulu/compare/v1.1.0...v1.2.0) (2026-07-28)


### Features

* **copier:** accounts API and the Accounts page ([b8af013](https://github.com/KasperSkytte/tradezulu/commit/b8af013a829895218625a9a641b4caf223b6c540))
* **copier:** execution layer, copy loop and a worker per account ([3570021](https://github.com/KasperSkytte/tradezulu/commit/3570021c038c1cca07f99325f2058be51d9f39d4))
* **mt5-bridge:** find a broker's own terminal, and pin the package version ([4b2fe2a](https://github.com/KasperSkytte/tradezulu/commit/4b2fe2a8f5c1b041d358aaf0ea9dafe560d311d7))


### Bug fixes

* **mt5-bridge:** do not crash on a fresh volume, and note the login finding ([a4973df](https://github.com/KasperSkytte/tradezulu/commit/a4973df5e46625a7164d78d09c170e271269beab))
* **mt5-bridge:** full Python install, Mono, win10, and honest readiness ([b4ce5f5](https://github.com/KasperSkytte/tradezulu/commit/b4ce5f56943064fa785b1791724c88d8bf1d034c))
* **mt5-bridge:** let the Python API own the terminal, and record what is ruled out ([bf3bd15](https://github.com/KasperSkytte/tradezulu/commit/bf3bd15ec676218dd81d3b2d1975539137823d2e))
* **mt5-bridge:** re-discover the terminal after a broker installer runs ([02e397a](https://github.com/KasperSkytte/tradezulu/commit/02e397a5c664537f82b559b35a200b34e9d32a55))
* **mt5-bridge:** run a window manager, and keep downloads off /tmp ([e5e0799](https://github.com/KasperSkytte/tradezulu/commit/e5e0799c2042fb29eadc18a2eaea8027db687f9c))


### Documentation

* write up the bridge IPC failure and stop claiming it works ([52e2bc8](https://github.com/KasperSkytte/tradezulu/commit/52e2bc89d6cbcd606fb50687b873f5ee614b68ac))

## [1.1.0](https://github.com/KasperSkytte/tradezulu/compare/v1.0.0...v1.1.0) (2026-07-27)


### Features

* **auth:** a way back in when TZ_ADMIN_USER no longer matches ([272c8b4](https://github.com/KasperSkytte/tradezulu/commit/272c8b478f44af28b9b4b264dac68794c5081140))


### Bug fixes

* **mt5-bridge:** pin Wine 10, update the prefix, and stop killing a live terminal ([e8daffd](https://github.com/KasperSkytte/tradezulu/commit/e8daffd16c05b19a6eab1383329f0578604f1bb5))

## 1.0.0 (2026-07-27)


### ⚠ BREAKING CHANGES

* **mt5:** the default sync mode is now 'bridge' rather than 'ea'. Existing installs keep whatever is stored in their settings.

### Features

* **backend:** trading journal API with MT5 sync, metrics and Zulu Score ([75b740c](https://github.com/KasperSkytte/tradezulu/commit/75b740ce93857a43d18738e0ae239187ee3bdf00))
* **ci:** GitHub Actions for lint, tests, image build and a container smoke ([c26f4e2](https://github.com/KasperSkytte/tradezulu/commit/c26f4e2f7a18a34c323e9adbc2df803d26f15d7a))
* **copier:** risk, sizing and copy-decision engine ([b5955f9](https://github.com/KasperSkytte/tradezulu/commit/b5955f9c39952243274faae385f32e1ac6e3b6ab))
* **docker:** single-container image, compose file and entrypoint ([c26f4e2](https://github.com/KasperSkytte/tradezulu/commit/c26f4e2f7a18a34c323e9adbc2df803d26f15d7a))
* **frontend:** dashboard, trades, calendar, reports and settings UI ([3be1329](https://github.com/KasperSkytte/tradezulu/commit/3be13294a2972d4e7441de29d812047b3e86f3df))
* **mt5:** Expert Advisor, optional Wine bridge and file import ([c26f4e2](https://github.com/KasperSkytte/tradezulu/commit/c26f4e2f7a18a34c323e9adbc2df803d26f15d7a))
* **mt5:** sync with just a server, account number and investor password ([170833d](https://github.com/KasperSkytte/tradezulu/commit/170833dd87af5d14fc1b898db98ab912ebb718da))
* **ui:** jade green accent, and position TradeZulu as copier plus journal ([0298a5a](https://github.com/KasperSkytte/tradezulu/commit/0298a5a08dd35226fdedbce025f9fd3e8beaba58))


### Bug fixes

* **charts:** give the TradingView widget a height it can resolve ([de65c83](https://github.com/KasperSkytte/tradezulu/commit/de65c8347e800acac029ada76e287bb774c20e3f))
* **charts:** render the trade replay and clean up derived money values ([d56dd47](https://github.com/KasperSkytte/tradezulu/commit/d56dd47123ae8c9b8facc9648f41aceaddcc6b1c))
* **db:** reconcile the schema on start so upgrades do not break ([e96617f](https://github.com/KasperSkytte/tradezulu/commit/e96617f0c70828a958127bf2c2b2ba7194c4a8ec))
* **mt5-bridge:** make the Wine container actually able to run MetaTrader ([0ab2153](https://github.com/KasperSkytte/tradezulu/commit/0ab21532150aef098db95442435f13ea5f65d335))
* **settings:** follow hash changes so deep links switch section ([3e5623e](https://github.com/KasperSkytte/tradezulu/commit/3e5623e8879f9adb16c33df85347ee50f9aad64a))


### Documentation

* make the compose image variables explicit in .env.example ([3e5623e](https://github.com/KasperSkytte/tradezulu/commit/3e5623e8879f9adb16c33df85347ee50f9aad64a))
* README, MetaTrader guide, metric definitions and deployment notes ([c26f4e2](https://github.com/KasperSkytte/tradezulu/commit/c26f4e2f7a18a34c323e9adbc2df803d26f15d7a))
* the README now leads with what this actually is — a trade copier and a ([0298a5a](https://github.com/KasperSkytte/tradezulu/commit/0298a5a08dd35226fdedbce025f9fd3e8beaba58))
* tighten the README for a public repo ([4f69491](https://github.com/KasperSkytte/tradezulu/commit/4f694911cbf91cd97195e3a543fae44f50a29297))


### Build & packaging

* **docker:** build the frontend on the native platform in multi-arch builds ([3e5623e](https://github.com/KasperSkytte/tradezulu/commit/3e5623e8879f9adb16c33df85347ee50f9aad64a))
* **docker:** mark the entrypoint executable ([b8b0a3d](https://github.com/KasperSkytte/tradezulu/commit/b8b0a3d7f7e0ef544480c51c2d2017528f1c9a59))
