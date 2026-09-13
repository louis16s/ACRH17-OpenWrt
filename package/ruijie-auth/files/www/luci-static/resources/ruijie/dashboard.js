/* Progressive layout for the Ruijie page.
 *
 * CBI renders every section as a plain <div class="cbi-section"> and gives
 * several of them the same id, so nothing here may key on an id or on a fixed
 * child position.  The button toolbars are laid out entirely by the stylesheet;
 * the sections that start folded are named by the CBI model through
 * data-ruijie-collapse, which keeps that list next to the definitions it refers
 * to instead of duplicating the titles in here.
 */
(function () {
	'use strict';

	function collapseTargets(map) {
		var panel = map.querySelector('.ruijie-dashboard');
		var names = panel && panel.getAttribute('data-ruijie-collapse');
		return names ? names.split('|').filter(Boolean) : [];
	}

	function makeCollapsible(section) {
		var node = section.querySelector('.cbi-section-node');
		if (!node || section.dataset.ruijieCollapsible) return;
		section.dataset.ruijieCollapsible = '1';
		section.classList.add('ruijie-collapsible');
		node.hidden = true;

		var toggle = document.createElement('button');
		toggle.type = 'button';
		toggle.className = 'btn cbi-button ruijie-collapse-toggle';
		toggle.setAttribute('aria-expanded', 'false');
		toggle.textContent = '展开手工参数';
		toggle.addEventListener('click', function () {
			var open = this.getAttribute('aria-expanded') === 'true';
			this.setAttribute('aria-expanded', open ? 'false' : 'true');
			this.textContent = open ? '展开手工参数' : '收起手工参数';
			node.hidden = open;
		});
		section.insertBefore(toggle, node);

		// A rejected value has to be visible, otherwise the save silently fails
		// on a field the user cannot see.
		if (section.querySelector('.cbi-value-error, .cbi-input-invalid')) toggle.click();
		node.addEventListener('invalid', function () {
			if (toggle.getAttribute('aria-expanded') === 'false') toggle.click();
		}, true);
	}

	function setup() {
		var map = document.getElementById('cbi-ruijie');
		if (!map) return;

		var names = collapseTargets(map);
		if (!names.length) return;
		var sections = map.querySelectorAll('.cbi-section');
		for (var i = 0; i < sections.length; i++) {
			var heading = sections[i].querySelector('h3');
			if (heading && names.indexOf(heading.textContent.trim()) !== -1) makeCollapsible(sections[i]);
		}
	}

	if (document.readyState === 'loading') {
		document.addEventListener('DOMContentLoaded', setup);
	} else {
		setup();
	}
}());
