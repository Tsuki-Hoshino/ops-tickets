/*
 * app.js —— 页面交互（原生 JS）
 *
 * 四件事，全部由模板里的元素 id 与属性驱动：
 *   1. 类别自动识别： #symptom 失焦时，若 #category 为空，
 *      读 <script type="application/json" id="category-keywords"> 里的
 *      [[关键词, 类别], ...]（按顺序匹配、先命中者胜、关键词与文本均转小写做包含判断，
 *      匹配文本 = symptom + ' ' + cause）并写入 #category 的值。
 *   2. 删除确认：带 data-confirm 的表单，submit 时 confirm(属性值)，取消则阻止提交。
 *   3. 报告周期联动：#period 变化时，只有 custom 显示并启用 #custom-range 内的日期输入，
 *      其余情况隐藏并禁用。
 *   4. 点开大图：a.photo-zoom 点击后弹遮罩层显示大图，ESC 或点击遮罩关闭，不新开窗口；
 *      JS 失效时链接本身仍可正常打开原图（href 指向图片，由 target 属性控制新窗口）。
 *
 * 约定：所有取元素的地方都判空，空状态下（元素不存在的页面）不报错。
 */
(function () {
  'use strict';

  /* ------------------------------------------------------------------
   * 1. 类别自动识别
   * ------------------------------------------------------------------ */

  /* 读取页面里注入的关键词表，失败返回空数组 */
  function readKeywordMap() {
    var node = document.getElementById('category-keywords');
    if (!node) {
      return [];
    }
    var raw;
    try {
      raw = JSON.parse(node.textContent || '[]');
    } catch (err) {
      return [];
    }
    if (!Array.isArray(raw)) {
      return [];
    }
    var map = [];
    raw.forEach(function (pair) {
      if (Array.isArray(pair) && pair.length >= 2 && pair[0] != null && pair[1] != null) {
        map.push([String(pair[0]).toLowerCase(), String(pair[1])]);
      }
    });
    return map;
  }

  /* 按顺序找第一个命中的类别，未命中返回空串 */
  function matchCategory(text, map) {
    var haystack = String(text || '').toLowerCase();
    if (!haystack.replace(/\s+/g, '')) {
      return '';
    }
    for (var i = 0; i < map.length; i++) {
      if (map[i][0] && haystack.indexOf(map[i][0]) !== -1) {
        return map[i][1];
      }
    }
    return '';
  }

  function initCategorySuggest() {
    var symptom = document.getElementById('symptom');
    var category = document.getElementById('category');
    if (!symptom || !category) {
      return;
    }

    var map = readKeywordMap();
    if (!map.length) {
      return;
    }

    symptom.addEventListener('blur', function () {
      /* 类别已经有值（用户手选或后端预填）就不动 */
      if (String(category.value || '').trim()) {
        return;
      }
      var cause = document.getElementById('cause');
      var text = String(symptom.value || '') + ' ' + (cause ? String(cause.value || '') : '');
      var hit = matchCategory(text, map);
      if (!hit) {
        return;
      }
      /* 只在下拉框里确实有这个类别时才写，避免写入不存在的值 */
      var exists = Array.prototype.some.call(category.options, function (option) {
        return option.value === hit;
      });
      if (exists) {
        category.value = hit;
      }
    });

    /* 原因字段同样参与匹配：填完原因后再回来失焦也能命中 */
    var causeInput = document.getElementById('cause');
    if (causeInput) {
      causeInput.addEventListener('blur', function () {
        if (String(category.value || '').trim()) {
          return;
        }
        var text = String(symptom.value || '') + ' ' + String(causeInput.value || '');
        var hit = matchCategory(text, map);
        if (!hit) {
          return;
        }
        var exists = Array.prototype.some.call(category.options, function (option) {
          return option.value === hit;
        });
        if (exists) {
          category.value = hit;
        }
      });
    }
  }

  /* ------------------------------------------------------------------
   * 2. 删除确认：任意带 data-confirm 的表单
   * ------------------------------------------------------------------ */

  function initConfirmForms() {
    var forms = document.querySelectorAll('form[data-confirm]');
    Array.prototype.forEach.call(forms, function (form) {
      form.addEventListener('submit', function (event) {
        var message = form.getAttribute('data-confirm') || '确定要执行该操作吗？';
        var ok = false;
        try {
          ok = window.confirm(message);
        } catch (err) {
          /* 极少数环境下 confirm 不可用：不阻断提交 */
          ok = true;
        }
        if (!ok) {
          event.preventDefault();
          event.stopPropagation();
        }
      });
    });
  }

  /* ------------------------------------------------------------------
   * 3. 报告周期联动：#custom-range 只在 custom 时显示并启用
   * ------------------------------------------------------------------ */

  function initPeriodToggle() {
    var period = document.getElementById('period');
    var range = document.getElementById('custom-range');
    if (!period || !range) {
      return;
    }

    var inputs = range.querySelectorAll('input, select, textarea');

    function apply() {
      var isCustom = period.value === 'custom';
      /* 直接写内联样式，样式表未加载时也能正确隐藏 */
      range.style.display = isCustom ? '' : 'none';
      Array.prototype.forEach.call(inputs, function (input) {
        input.disabled = !isCustom;
      });
    }

    period.addEventListener('change', apply);
    /* 进入页面时按当前值同步一次（后端回填 custom 时能直接编辑区间） */
    apply();
  }

  /* ------------------------------------------------------------------
   * 4. 点开大图：遮罩层显示，ESC 或点击遮罩关闭
   * ------------------------------------------------------------------ */

  function initPhotoZoom() {
    var links = document.querySelectorAll('a.photo-zoom');
    if (!links.length) {
      return;
    }

    var mask = null;
    var figure = null;
    /* 记录打开前的滚动位置，关闭后恢复，避免页面跳动 */
    var scrollTop = 0;

    function close() {
      if (!mask) {
        return;
      }
      mask.style.display = 'none';
      if (figure) {
        figure.removeAttribute('src');
      }
      document.body.style.overflow = '';
      window.scrollTo(0, scrollTop);
      document.removeEventListener('keydown', onKeydown, true);
    }

    function onKeydown(event) {
      if (event.key === 'Escape' || event.keyCode === 27) {
        event.preventDefault();
        close();
      }
    }

    function ensureMask() {
      if (mask) {
        return mask;
      }
      mask = document.createElement('div');
      mask.className = 'photo-zoom-mask';
      mask.setAttribute('role', 'dialog');
      mask.setAttribute('aria-label', '照片预览');
      mask.style.display = 'none';

      figure = document.createElement('img');
      figure.alt = '照片预览';
      mask.appendChild(figure);

      /* 点击遮罩本身（不是图片）关闭 */
      mask.addEventListener('click', function (event) {
        if (event.target === mask) {
          close();
        }
      });
      document.body.appendChild(mask);
      return mask;
    }

    Array.prototype.forEach.call(links, function (link) {
      link.addEventListener('click', function (event) {
        var href = link.getAttribute('href') || '';
        /* 没有可用地址时不接管，交给浏览器的默认行为 */
        if (!href || href.charAt(0) === '#') {
          return;
        }
        /* 只接管左键单击；中键、Ctrl 点击等交给浏览器原生行为 */
        if (event.defaultPrevented || event.button !== 0 ||
            event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
          return;
        }
        event.preventDefault();

        var box = ensureMask();
        scrollTop = window.pageYOffset || document.documentElement.scrollTop || 0;
        figure.setAttribute('src', href);
        box.style.display = 'flex';
        document.body.style.overflow = 'hidden';
        document.addEventListener('keydown', onKeydown, true);
      });
    });
  }

  /* ------------------------------------------------------------------
   * 启动
   * ------------------------------------------------------------------ */

  function init() {
    /* 每块各自 try 包裹：任一页面的元素缺失都不影响其他交互 */
    var tasks = [initCategorySuggest, initConfirmForms, initPeriodToggle, initPhotoZoom];
    tasks.forEach(function (task) {
      try {
        task();
      } catch (err) {
        /* 静默：交互增强失败不应影响页面基本可用性 */
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
