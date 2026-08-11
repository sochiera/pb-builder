.PHONY: smoke ci hardware

smoke:
	python3 -m unittest discover -s tests -v

ci: smoke
	python3 -m compileall -q app.py

hardware:
	python3 -c "from app import analyze; assert analyze({'cpu': 'r5-7600', 'motherboard': 'b650m', 'ram': 'ddr5-32', 'gpu': 'rtx-5060', 'psu': '650w', 'case': 'm-atx-compact'})['isCompatible']; print('hardware profile passed')"
