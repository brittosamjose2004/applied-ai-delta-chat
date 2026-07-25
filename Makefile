.PHONY: install samples run chat eval test web markup cost-report

install:
	pip install -r requirements.txt

samples:
	python scripts/make_samples.py

run:
	python -m src.cli run \
		--pid-a PID-A --path-a data/samples/pair_01_lift_gas_compressor/rev_A_native.pdf \
		--pid-b PID-B --path-b data/samples/pair_01_lift_gas_compressor/rev_B_native.pdf \
		--out data/samples/pair_01_lift_gas_compressor/output

chat:
	python -m src.cli chat \
		--pid-a PID-A --path-a data/samples/pair_01_lift_gas_compressor/rev_A_native.pdf \
		--pid-b PID-B --path-b data/samples/pair_01_lift_gas_compressor/rev_B_native.pdf

markup:
	python -m src.cli markup \
		--pid-a PID-A --path-a data/samples/pair_01_lift_gas_compressor/rev_A_native.pdf \
		--pid-b PID-B --path-b data/samples/pair_01_lift_gas_compressor/rev_B_native.pdf \
		--out data/samples/pair_01_lift_gas_compressor/output/rev_B_markup.pdf

eval:
	python -m eval.run_eval

test:
	python -m pytest tests/ -q

web:
	uvicorn src.web.app:app --reload --port 8000

cost-report:
	python -m eval.cost_analysis
