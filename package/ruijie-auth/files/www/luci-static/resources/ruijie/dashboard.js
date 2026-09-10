(function () {
	'use strict';

	function setupManualSection() {
		var sections = document.querySelectorAll('.cbi-section');

		for (var i = 0; i < sections.length; i++) {
			var section = sections[i];
			var heading = section.querySelector('h3');
			var node = section.querySelector('.cbi-section-node');

			if (!heading || !node || heading.textContent.indexOf('认证参数') === -1 || section.dataset.ruijieManual) {
				continue;
			}

			section.dataset.ruijieManual = '1';
			section.classList.add('ruijie-manual-section', 'is-collapsed');
			node.hidden = true;

			var toggle = document.createElement('button');
			toggle.type = 'button';
			toggle.className = 'btn cbi-button ruijie-manual-toggle';
			toggle.setAttribute('aria-expanded', 'false');
			toggle.textContent = '展开手工参数';
			toggle.addEventListener('click', function () {
				var open = this.getAttribute('aria-expanded') === 'true';
				var parent = this.closest('.ruijie-manual-section');
				this.setAttribute('aria-expanded', open ? 'false' : 'true');
				this.textContent = open ? '展开手工参数' : '收起手工参数';
				parent.classList.toggle('is-collapsed', open);
				parent.querySelector('.cbi-section-node').hidden = open;
			});
			section.insertBefore(toggle, node);
			if (section.querySelector('.cbi-value-error, .cbi-input-invalid')) toggle.click();
			node.addEventListener('invalid', function () {
				var parent = this.closest('.ruijie-manual-section');
				var button = parent.querySelector('.ruijie-manual-toggle');
				if (button.getAttribute('aria-expanded') === 'false') button.click();
			}, true);
		}
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', setupManualSection);
	} else {
		setupManualSection();
	}
}());
