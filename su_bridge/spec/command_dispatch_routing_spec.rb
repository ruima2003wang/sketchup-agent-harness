# frozen_string_literal: true

require_relative "spec_helper"
require "su_bridge"

# Operation routing contract for the bridge.
#
# These examples run without a SketchUp process: spec_helper supplies the
# Sketchup/UI/Geom fakes and each handler is stubbed, so only the mapping from
# operation_type to handler (and the response envelope around it) is under
# test. The Python side of the same contract is checked offline by
# mcp_server/tests/test_ruby_bridge_contract.py.
RSpec.describe "SuBridge::CommandDispatcher operation routing" do
  let(:dispatcher) { SuBridge::CommandDispatcher.new }

  before do
    allow(SuBridge).to receive(:design_sync).and_return(nil)
  end

  describe "OPERATION_HANDLERS routing" do
    SuBridge::CommandDispatcher::OPERATION_HANDLERS.each do |operation_type, handler|
      it "routes #{operation_type} to ##{handler}" do
        allow(dispatcher).to receive(handler).and_return({ entity_ids: [] })

        response = dispatcher.dispatch_operation("op_#{operation_type}", operation_type, {})

        expect(dispatcher).to have_received(handler).with({})
        expect(response[:operation_id]).to eq("op_#{operation_type}")
        expect(response[:status]).to eq("success")
      end
    end
  end

  describe "handler table integrity" do
    it "defines every routed handler as a private method" do
      SuBridge::CommandDispatcher::OPERATION_HANDLERS.each_value do |handler|
        expect(dispatcher.private_methods).to include(handler), "missing ##{handler}"
      end
    end

    it "only lists operations that have a handler" do
      routed = SuBridge::CommandDispatcher::OPERATION_HANDLERS.keys
      special = SuBridge::CommandDispatcher::TRANSACTIONAL_OPERATIONS.to_a +
                SuBridge::CommandDispatcher::ENTITY_MODIFYING_OPERATIONS.to_a

      expect(special - routed).to be_empty
    end
  end

  describe "#dispatch_operation with an unknown operation_type" do
    it "returns a JSON-RPC error without calling a handler" do
      response = dispatcher.dispatch_operation("op_missing", "not_a_real_operation", {})

      expect(response["error"]["code"]).to eq(-32000)
      expect(response["error"]["message"]).to include("not_a_real_operation")
      expect(response["error"]["data"]["operation_id"]).to eq("op_missing")
    end
  end

  describe "#dispatch" do
    it "returns the handler result for execute_operation" do
      allow(dispatcher).to receive(:handle_get_bridge_info)
        .and_return({ bridge_info: { version: "test" } })

      response = dispatcher.dispatch(
        "method" => "execute_operation",
        "params" => {
          "operation_id" => "op_dispatch",
          "operation_type" => "get_bridge_info",
          "payload" => {},
          "rollback_on_failure" => false,
        },
        "id" => 7
      )

      expect(dispatcher).to have_received(:handle_get_bridge_info).with({})
      expect(response[:operation_id]).to eq("op_dispatch")
      expect(response[:status]).to eq("success")
      expect(response[:bridge_info][:version]).to eq("test")
    end

    it "rejects unknown methods" do
      response = dispatcher.dispatch("method" => "not_a_method", "params" => {}, "id" => 8)

      expect(response["error"]["code"]).to eq(-32000)
      expect(response["id"]).to eq(8)
    end
  end

  describe "transaction wrapping" do
    it "wraps transactional operations and defaults rollback_on_failure to true" do
      allow(SuBridge::UndoManager).to receive(:with_transaction).and_call_original
      allow(dispatcher).to receive(:handle_create_wall).and_return({ entity_ids: [] })

      dispatcher.dispatch(
        "method" => "execute_operation",
        "params" => { "operation_type" => "create_wall" },
        "id" => 9
      )

      expect(SuBridge::UndoManager).to have_received(:with_transaction)
        .with(name: "create_wall", rollback_on_failure: true)
    end

    it "does not wrap read-only operations" do
      allow(SuBridge::UndoManager).to receive(:with_transaction).and_call_original
      allow(dispatcher).to receive(:handle_get_scene_info).and_return({})

      dispatcher.dispatch_operation("op_read", "get_scene_info", {})

      expect(SuBridge::UndoManager).not_to have_received(:with_transaction)
    end
  end

  describe "handler failures" do
    it "maps validation errors to -32001 and reports a skipped rollback" do
      allow(dispatcher).to receive(:handle_create_box)
        .and_raise(SuBridge::UndoManager::ValidationError, "box cannot be created")

      response = dispatcher.dispatch_operation("op_bad_box", "create_box", {}, false)

      expect(response["error"]["code"]).to eq(-32001)
      expect(response["error"]["message"]).to eq("box cannot be created")
      expect(response["error"]["data"]["rollback_status"]).to eq("skipped")
    end
  end
end
