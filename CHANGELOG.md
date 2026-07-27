# Changelog

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
