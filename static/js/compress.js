/*
 * compress.js —— 照片前端静默压缩（原生 JS）
 *
 * 用户选中照片后，在浏览器端用 canvas 压缩到最长边 1600px、
 * JPEG 质量 0.78；压缩后重建 FileList 写回 input，保证表单正常提交；
 * 压缩失败则回退原图，绝不阻断提交；页面上给出压缩前后体积对比。
 *
 * 绑定方式（全部由 input 上的属性驱动）：
 *   <input type="file" multiple data-photo-compress
 *          data-max-edge="1600" data-quality="0.78"
 *          data-photo-summary="#before-summary">
 *   - 选择器：input[type=file][data-photo-compress]
 *   - data-max-edge    最长边像素，默认 1600
 *   - data-quality     JPEG 质量，默认 0.78
 *   - data-photo-summary 展示体积对比的元素选择器（可省略，省略则只压缩不展示）
 *
 * 已知取舍：不读取、不纠正 EXIF 方向。手机竖拍照片在某些
 * 浏览器里会按原始像素方向压缩，方向最终由浏览器按 EXIF 自行渲染。
 *
 * 对表单的其他部分零影响：任何异常都在本文件内吞掉并回退原图。
 */
(function () {
  'use strict';

  /* 默认参数：最长边 1600px、JPEG 质量 0.78 */
  var DEFAULT_MAX_EDGE = 1600;
  var DEFAULT_QUALITY = 0.78;

  /* 只处理浏览器通常能解码的图片类型；其余（如 heic、pdf）一律原样放过 */
  var IMAGE_TYPE_RE = /^image\/(jpeg|jpg|png|webp|bmp|gif)$/i;

  /* 字节数 → 人类可读文本，例如 3.2 MB / 780 KB / 512 B */
  function formatSize(bytes) {
    if (!isFinite(bytes) || bytes < 0) {
      return '未知';
    }
    if (bytes < 1024) {
      return bytes + ' B';
    }
    if (bytes < 1024 * 1024) {
      return (bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0) + ' KB';
    }
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  /* 保留原文件名主体，扩展名统一改为 .jpg；压缩回退时不改名 */
  function toJpegName(name) {
    var base = String(name || 'photo');
    var dot = base.lastIndexOf('.');
    if (dot > 0) {
      base = base.slice(0, dot);
    }
    return (base || 'photo') + '.jpg';
  }

  /* 读取元素上的数值参数，非法或缺失时用默认值 */
  function readNumber(el, attr, fallback) {
    var value = parseFloat(el.getAttribute(attr));
    return isFinite(value) && value > 0 ? value : fallback;
  }

  /* 按最长边计算目标尺寸；原本就小于目标尺寸时返回原尺寸 */
  function fitSize(width, height, maxEdge) {
    var longest = Math.max(width, height);
    if (!longest || longest <= maxEdge) {
      return { width: Math.max(1, Math.round(width)), height: Math.max(1, Math.round(height)) };
    }
    var scale = maxEdge / longest;
    return {
      width: Math.max(1, Math.round(width * scale)),
      height: Math.max(1, Math.round(height * scale))
    };
  }

  /* 解码图片。优先 createImageBitmap，不支持时退回 Image + ObjectURL */
  function loadImage(file) {
    if (typeof window.createImageBitmap === 'function') {
      return window.createImageBitmap(file).catch(function () {
        return loadImageByElement(file);
      });
    }
    return loadImageByElement(file);
  }

  function loadImageByElement(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        /* 图片已解码进内存，可以立即释放 URL，避免内存泄漏 */
        URL.revokeObjectURL(url);
        resolve(img);
      };
      img.onerror = function () {
        /* 失败路径同样要释放，否则 URL 一直挂着 */
        URL.revokeObjectURL(url);
        reject(new Error('图片解码失败'));
      };
      img.src = url;
    });
  }

  /* canvas → JPEG Blob */
  function canvasToBlob(canvas, quality) {
    return new Promise(function (resolve, reject) {
      if (typeof canvas.toBlob !== 'function') {
        reject(new Error('当前浏览器不支持 canvas.toBlob'));
        return;
      }
      canvas.toBlob(function (blob) {
        if (blob) {
          resolve(blob);
        } else {
          reject(new Error('canvas 导出失败'));
        }
      }, 'image/jpeg', quality);
    });
  }

  /* 压缩单张图片。任何失败都 reject，由调用方回退原图。 */
  function compressImage(file, maxEdge, quality) {
    return loadImage(file).then(function (source) {
      var sourceWidth = source.width || source.naturalWidth || 0;
      var sourceHeight = source.height || source.naturalHeight || 0;
      if (!sourceWidth || !sourceHeight) {
        throw new Error('无法取得图片尺寸');
      }

      var target = fitSize(sourceWidth, sourceHeight, maxEdge);
      var canvas = document.createElement('canvas');
      canvas.width = target.width;
      canvas.height = target.height;

      var ctx = canvas.getContext('2d');
      if (!ctx) {
        throw new Error('无法创建 canvas 上下文');
      }
      /* JPEG 无透明通道，先铺白底，避免 PNG 透明区域变黑 */
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, target.width, target.height);
      ctx.drawImage(source, 0, 0, target.width, target.height);

      if (source.close) {
        source.close();
      }

      return canvasToBlob(canvas, quality).then(function (blob) {
        return {
          blob: blob,
          width: target.width,
          height: target.height
        };
      });
    });
  }

  /* 用 DataTransfer 重建 FileList 并写回 input；不支持时返回 false */
  function writeBack(input, files) {
    try {
      var dt = new DataTransfer();
      for (var i = 0; i < files.length; i++) {
        dt.items.add(files[i]);
      }
      input.files = dt.files;
      return true;
    } catch (err) {
      /* 极老浏览器不支持给 input.files 赋值：保持原 FileList，表单照常提交原图 */
      return false;
    }
  }

  /* 处理一个 input 上的全部选中文件 */
  function processInput(input) {
    var originals = Array.prototype.slice.call(input.files || []);
    if (!originals.length) {
      return Promise.resolve();
    }

    var maxEdge = readNumber(input, 'data-max-edge', DEFAULT_MAX_EDGE);
    var quality = readNumber(input, 'data-quality', DEFAULT_QUALITY);

    return Promise.all(originals.map(function (file) {
      /* 非图片或读取失败：当作原图处理，不阻断 */
      if (!file || !IMAGE_TYPE_RE.test(file.type || '')) {
        return { file: file, originalSize: file ? file.size : 0, size: file ? file.size : 0, compressed: false };
      }
      return compressImage(file, maxEdge, quality).then(function (result) {
        /* 体积没变小就不替换，宁可上传原图也不让画质白白损失 */
        if (!result.blob || result.blob.size >= file.size) {
          return { file: file, originalSize: file.size, size: file.size, compressed: false };
        }
        try {
          var next = new File([result.blob], toJpegName(file.name), {
            type: 'image/jpeg',
            lastModified: file.lastModified || Date.now()
          });
          return { file: next, originalSize: file.size, size: next.size, compressed: true };
        } catch (err) {
          return { file: file, originalSize: file.size, size: file.size, compressed: false };
        }
      }).catch(function () {
        /* 压缩失败一律回退原图 */
        return { file: file, originalSize: file.size, size: file.size, compressed: false };
      });
    })).then(function (items) {
      var usable = items.filter(function (item) {
        return item.file;
      });
      if (!usable.length) {
        return;
      }
      writeBack(input, usable.map(function (item) {
        return item.file;
      }));
      renderSummary(input, usable);
    });
  }

  /* 把「压缩前 x → 压缩后 y（省 z%）」写进 data-photo-summary 指向的元素 */
  function renderSummary(input, items) {
    var selector = input.getAttribute('data-photo-summary');
    if (!selector) {
      return;
    }
    var target;
    try {
      target = document.querySelector(selector);
    } catch (err) {
      target = null;
    }
    if (!target) {
      return;
    }

    var before = 0;
    var after = 0;
    var changed = 0;
    items.forEach(function (item) {
      before += item.originalSize || 0;
      after += item.size || 0;
      if (item.compressed) {
        changed += 1;
      }
    });

    var text = '压缩前 ' + formatSize(before) + ' → 压缩后 ' + formatSize(after);
    if (before > 0 && after < before) {
      text += '（省 ' + Math.round((1 - after / before) * 100) + '%）';
    }
    if (changed < items.length) {
      text += '；' + (items.length - changed) + ' 张保持原图';
    }
    target.textContent = text;
  }

  function initCompress() {
    var inputs = document.querySelectorAll('input[type=file][data-photo-compress]');
    Array.prototype.forEach.call(inputs, function (input) {
      input.addEventListener('change', function () {
        /* 全程静默：不弹任何提示；异常也不抛出，避免影响表单提交 */
        try {
          processInput(input).catch(function () {
            /* 静默失败，input 内仍是原图 */
          });
        } catch (err) {
          /* 静默失败 */
        }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCompress);
  } else {
    initCompress();
  }

  /* 暴露出来，便于在需要时手动触发 */
  window.PhotoCompress = {
    formatSize: formatSize,
    process: processInput
  };
})();
