package io.github.santiesc06.series76.ui.login

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.santiesc06.series76.data.ApiResult
import io.github.santiesc06.series76.data.auth.AuthRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class LoginUiState(
    val email: String = "",
    val password: String = "",
    val signingIn: Boolean = false,
    val error: String? = null,
) {
    val canSubmit: Boolean get() = email.isNotBlank() && password.isNotEmpty() && !signingIn
}

@HiltViewModel
class LoginViewModel @Inject constructor(private val auth: AuthRepository) : ViewModel() {

    private val _state = MutableStateFlow(LoginUiState())
    val state: StateFlow<LoginUiState> = _state.asStateFlow()

    fun onEmailChange(value: String) = _state.update { it.copy(email = value, error = null) }

    fun onPasswordChange(value: String) = _state.update { it.copy(password = value, error = null) }

    /** A success switches the app to the conversations list (the session state changes). */
    fun submit() {
        val current = _state.value
        if (!current.canSubmit) return
        _state.update { it.copy(signingIn = true, error = null) }
        viewModelScope.launch {
            when (val result = auth.login(current.email, current.password)) {
                // The password is not kept once it has been used.
                is ApiResult.Ok -> _state.update { it.copy(password = "", signingIn = false) }
                is ApiResult.Err -> _state.update {
                    it.copy(password = "", signingIn = false, error = result.error.message)
                }
            }
        }
    }
}
