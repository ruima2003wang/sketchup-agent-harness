# frozen_string_literal: true

require_relative "spec_helper"
require "su_bridge/entities/component_manager"

# Component placement matrix composition.
#
# create_transform builds `translation * rotation * scale`: the placement point
# is translated last, so rotation and scale happen around the component origin
# and never move the placement position itself. These examples pin that order
# with real matrix math instead of the old `Transformation#*` stub (which
# returned self and could not tell any order apart).
RSpec.describe SuBridge::Entities::ComponentManager do
  describe ".create_transform" do
    def millimetres_to_inches(millimetres)
      millimetres / 25.4
    end

    def placement_translation(millimetres)
      Geom::Transformation.translation(
        Geom::Vector3d.new(*millimetres.map { |value| millimetres_to_inches(value) })
      )
    end

    def expect_same_matrix(actual, expected, tolerance = 1e-9)
      actual_values = actual.to_a
      expected_values = expected.to_a
      expect(actual_values.length).to eq(expected_values.length)
      actual_values.each_with_index do |value, index|
        expect(value).to be_within(tolerance).of(expected_values[index]),
          "matrix element #{index}: expected #{expected_values[index]}, got #{value}"
      end
    end

    it "is the identity for the world origin with no rotation or scale" do
      transform = described_class.create_transform([0, 0, 0], 0, 1.0)

      expect_same_matrix(transform, Geom::Transformation.new)
    end

    it "converts the placement position from millimetres to inches" do
      transform = described_class.create_transform([1000, 2000, 3000], 0, 1.0)

      expect_same_matrix(transform, placement_translation([1000, 2000, 3000]))
    end

    it "composes translation * rotation when only rotation is set" do
      transform = described_class.create_transform([1000, 0, 0], 90, 1.0)

      expected = placement_translation([1000, 0, 0]) *
                 Geom::Transformation.rotation(ORIGIN, Z_AXIS, 90.degrees)

      expect_same_matrix(transform, expected)
    end

    it "composes translation * scale when only scale is set" do
      transform = described_class.create_transform([1000, 0, 0], 0, 2.0)

      expected = placement_translation([1000, 0, 0]) *
                 Geom::Transformation.scaling(ORIGIN, 2.0)

      expect_same_matrix(transform, expected)
    end

    it "composes translation * rotation * scale when both are set" do
      transform = described_class.create_transform([1000, 0, 0], 90, 2.0)

      expected = placement_translation([1000, 0, 0]) *
                 Geom::Transformation.rotation(ORIGIN, Z_AXIS, 90.degrees) *
                 Geom::Transformation.scaling(ORIGIN, 2.0)

      expect_same_matrix(transform, expected)
    end

    it "keeps the placement origin at the requested position under rotation and scale" do
      transform = described_class.create_transform([1000, 0, 0], 90, 2.0)

      expect(transform.origin.x).to be_within(1e-9).of(millimetres_to_inches(1000))
      expect(transform.origin.y).to be_within(1e-9).of(0.0)
      expect(transform.origin.z).to be_within(1e-9).of(0.0)
    end

    it "rotates and scales the local axes instead of the placement point" do
      transform = described_class.create_transform([1000, 0, 0], 90, 2.0)

      values = transform.to_a

      # Local X maps to (0, 2, 0) and local Y maps to (-2, 0, 0): rotation of
      # 90 degrees around Z, scaled by 2 about the component origin.
      expect(values[0]).to be_within(1e-9).of(0.0)
      expect(values[4]).to be_within(1e-9).of(2.0)
      expect(values[1]).to be_within(1e-9).of(-2.0)
      expect(values[5]).to be_within(1e-9).of(0.0)
      expect(values[10]).to be_within(1e-9).of(2.0)

      # The translation column stays the requested placement position.
      expect(values[3]).to be_within(1e-9).of(millimetres_to_inches(1000))
      expect(values[7]).to be_within(1e-9).of(0.0)
      expect(values[11]).to be_within(1e-9).of(0.0)
    end
  end
end
