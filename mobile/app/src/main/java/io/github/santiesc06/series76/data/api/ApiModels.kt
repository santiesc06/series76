package io.github.santiesc06.series76.data.api

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement

// Mirrors backend/app/api/schemas.py (design §4.1). Unknown fields are ignored, so the backend
// can add fields without breaking the app.

@Serializable
data class ConversationRequest(
    @SerialName("session_id") val sessionId: String? = null,
    val query: String,
)

@Serializable
data class SpecValue(
    val value: Double? = null,
    val unit: String,
    val condition: String? = null,
)

@Serializable
data class Spec(
    val key: String,
    val label: String,
    val values: List<SpecValue>,
)

@Serializable
data class SpecGroup(
    val key: String,
    val title: String,
    val specs: List<Spec>,
)

@Serializable
data class PowerSupply(
    val label: String,
    val voltage: Int,
    val phase: String? = null,
    @SerialName("current_type") val currentType: String,
)

@Serializable
data class Product(
    @SerialName("part_number") val partNumber: String,
    @SerialName("model_code") val modelCode: String,
    val enclosure: String,
    @SerialName("power_supply") val powerSupply: PowerSupply,
    val certifications: List<String> = emptyList(),
    @SerialName("hazardous_markings") val hazardousMarkings: List<String> = emptyList(),
    @SerialName("data_available") val dataAvailable: Boolean = true,
    val notes: List<String> = emptyList(),
    val highlight: List<String> = emptyList(),
    @SerialName("match_note") val matchNote: String? = null,
    @SerialName("spec_groups") val specGroups: List<SpecGroup> = emptyList(),
)

@Serializable
data class QuickReply(
    val label: String,
    val message: String,
)

@Serializable
data class ConversationResponse(
    @SerialName("session_id") val sessionId: String,
    @SerialName("message_id") val messageId: String,
    val answer: String,
    val status: String,
    val view: String,
    val products: List<Product> = emptyList(),
    val alternatives: List<Product> = emptyList(),
    @SerialName("quick_replies") val quickReplies: List<QuickReply> = emptyList(),
    @SerialName("created_at") val createdAt: String,
)

@Serializable
data class SessionSummary(
    val id: String,
    val title: String,
    @SerialName("created_at") val createdAt: String,
    @SerialName("updated_at") val updatedAt: String,
    @SerialName("message_count") val messageCount: Int = 0,
)

@Serializable
data class HistoryMessage(
    val id: String,
    val role: String,
    val content: String,
    @SerialName("created_at") val createdAt: String,
    val status: String? = null,
    val view: String? = null,
    val products: List<Product> = emptyList(),
    val alternatives: List<Product> = emptyList(),
    @SerialName("quick_replies") val quickReplies: List<QuickReply> = emptyList(),
)

@Serializable
data class SessionMessages(
    @SerialName("session_id") val sessionId: String,
    val title: String,
    val messages: List<HistoryMessage>,
)

// Voice message transcript (US-22).
@Serializable
data class TranscribeResponse(
    val text: String,
    val language: String,
    @SerialName("duration_s") val durationS: Double,
)

// Login (US-21, design U1/U4).
@Serializable
data class LoginRequest(val email: String, val password: String)

@Serializable
data class UserOut(val id: String, val email: String, val name: String)

@Serializable
data class LoginResponse(
    val token: String,
    @SerialName("expires_at") val expiresAt: String,
    val user: UserOut,
)

@Serializable
data class ErrorBody(val code: String, val message: String)

@Serializable
data class ErrorResponse(val error: ErrorBody)

// Developer-only (design C2, US-19): served by /api/messages/{id}/debug.
@Serializable
data class DebugStep(
    val tool: String,
    val args: JsonElement? = null,
    val result: JsonElement? = null,
    @SerialName("duration_ms") val durationMs: Int? = null,
    val error: String? = null,
)

@Serializable
data class TokenUsage(val input: Int = 0, val output: Int = 0)

@Serializable
data class DebugInfo(
    @SerialName("message_id") val messageId: String,
    val model: String? = null,
    @SerialName("latency_ms") val latencyMs: Int? = null,
    @SerialName("model_calls") val modelCalls: Int? = null,
    val tokens: TokenUsage? = null,
    @SerialName("estimated_cost_usd") val estimatedCostUsd: Double? = null,
    val steps: List<DebugStep> = emptyList(),
    @SerialName("number_check") val numberCheck: JsonElement? = null,
    @SerialName("rejected_refs") val rejectedRefs: List<String> = emptyList(),
    @SerialName("slot_fix") val slotFix: String? = null,
    @SerialName("context_note") val contextNote: String? = null,
)
