# frozen_string_literal: true

require "rspec"
require "fileutils"
require "json"
require "tmpdir"

$LOAD_PATH.unshift(File.expand_path("../lib", __dir__))

module Sketchup
  class ModelObserver; end
  class Face; end
  class Edge; end
  class Group; end
  class ComponentInstance; end

  class FakeModel
    def start_operation(_name, _disable_ui = true); end
    def commit_operation; end
    def abort_operation; end
  end

  def self.active_model
    @active_model ||= FakeModel.new
  end
end

SketchUp = Sketchup unless defined?(SketchUp)

module UI
  def self.start_timer(_interval, _repeat = false)
    yield if block_given?
  end
end

module Geom
  class Point3d
    attr_reader :x, :y, :z

    def initialize(x = 0, y = 0, z = 0)
      @x = x.to_f
      @y = y.to_f
      @z = z.to_f
    end

    def to_a
      [x, y, z]
    end
  end

  class Vector3d < Point3d; end

  # Real 4x4 affine matrix instead of the old "return self" stub, so specs can
  # tell composition order apart. SketchUp matrices are row-major and points
  # are column vectors: applying +matrix+ to a point means +matrix * point+,
  # therefore +a * b+ applies +b+ first and +a+ second.
  class Transformation
    ROW_COUNT = 4

    IDENTITY = [
      [1.0, 0.0, 0.0, 0.0],
      [0.0, 1.0, 0.0, 0.0],
      [0.0, 0.0, 1.0, 0.0],
      [0.0, 0.0, 0.0, 1.0],
    ].freeze

    # Accepts no argument (identity), a Point3d (translation), another
    # Transformation (copy) or 4 rows / 16 values (explicit matrix).
    def initialize(source = nil)
      @rows = rows_from(source)
    end

    def self.translation(vector)
      new(Point3d.new(vector.x, vector.y, vector.z))
    end

    def self.rotation(point, axis, angle)
      new(point) *
        new(axis_rotation_rows(axis, angle)) *
        new(Point3d.new(-point.x, -point.y, -point.z))
    end

    def self.scaling(*args)
      point = args.first.is_a?(Point3d) ? args.shift : nil
      factors = args.length == 1 ? [args.first] * 3 : args
      unless factors.length == 3
        raise ArgumentError, "scaling expects one factor or three factors"
      end

      scale_rows = [
        [factors[0].to_f, 0.0, 0.0, 0.0],
        [0.0, factors[1].to_f, 0.0, 0.0],
        [0.0, 0.0, factors[2].to_f, 0.0],
        [0.0, 0.0, 0.0, 1.0],
      ]
      point ? new(point) * new(scale_rows) * new(Point3d.new(-point.x, -point.y, -point.z)) : new(scale_rows)
    end

    def *(other)
      unless other.is_a?(Transformation)
        raise TypeError, "cannot multiply Transformation by #{other.class}"
      end

      product = Array.new(ROW_COUNT) do |row|
        Array.new(ROW_COUNT) do |column|
          (0...ROW_COUNT).sum { |index| @rows[row][index] * other.rows[index][column] }
        end
      end
      Transformation.new(product)
    end

    def origin
      Point3d.new(@rows[0][3], @rows[1][3], @rows[2][3])
    end

    def to_a
      @rows.flatten
    end

    # Supports both SketchUp forms: +transformation[row, column]+ and the
    # flattened +transformation[index]+.
    def [](row, column = nil)
      return to_a[row] if column.nil?

      @rows[row][column]
    end

    protected

    def rows
      @rows
    end

    class << self
      private

      # Rodrigues rotation about an axis through the world origin.
      def axis_rotation_rows(axis, angle)
        length = Math.sqrt((axis.x * axis.x) + (axis.y * axis.y) + (axis.z * axis.z))
        raise ArgumentError, "rotation axis must not be zero" if length.zero?

        x = axis.x / length
        y = axis.y / length
        z = axis.z / length
        cosine = Math.cos(angle)
        sine = Math.sin(angle)
        versine = 1.0 - cosine

        [
          [versine * x * x + cosine, versine * x * y - sine * z, versine * x * z + sine * y, 0.0],
          [versine * x * y + sine * z, versine * y * y + cosine, versine * y * z - sine * x, 0.0],
          [versine * x * z - sine * y, versine * y * z + sine * x, versine * z * z + cosine, 0.0],
          [0.0, 0.0, 0.0, 1.0],
        ]
      end
    end

    private

    def rows_from(source)
      case source
      when nil
        copy_rows(IDENTITY)
      when Point3d
        translation_rows(source)
      when Transformation
        copy_rows(source.rows)
      when Array
        rows = source.length == ROW_COUNT ? source : source.each_slice(ROW_COUNT).to_a
        copy_rows(rows)
      else
        raise ArgumentError, "unsupported Transformation source: #{source.inspect}"
      end
    end

    def translation_rows(point)
      [
        [1.0, 0.0, 0.0, point.x],
        [0.0, 1.0, 0.0, point.y],
        [0.0, 0.0, 1.0, point.z],
        [0.0, 0.0, 0.0, 1.0],
      ]
    end

    def copy_rows(rows)
      Array.new(ROW_COUNT) do |row|
        Array.new(ROW_COUNT) { |column| rows[row][column].to_f }
      end
    end
  end
end

ORIGIN = Geom::Point3d.new(0, 0, 0) unless defined?(ORIGIN)
Z_AXIS = Geom::Vector3d.new(0, 0, 1) unless defined?(Z_AXIS)

class Numeric
  def degrees
    self * Math::PI / 180.0
  end

  def to_mm
    self * 25.4
  end
end
