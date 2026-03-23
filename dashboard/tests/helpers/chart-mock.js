// Chart.js mock for tests — records constructor calls, provides destroy/update stubs
export class Chart {
  constructor(canvas, config) {
    this.canvas = canvas;
    this.config = config;
    this.destroyed = false;
    this.data = config?.data || {};
    this.options = config?.options || {};
    Chart.instances.push(this);
  }

  destroy() {
    this.destroyed = true;
  }

  update() {}

  resize() {}

  static instances = [];

  static reset() {
    Chart.instances = [];
  }

  static register() {}
}
