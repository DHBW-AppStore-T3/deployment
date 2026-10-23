// Evaluates a ValidatingAdmissionPolicy against admission requests the way
// kube-apiserver does (same compiler, environment, variables, match
// conditions and validator as k8s.io/apiserver's validating plugin).
//
//	go run . <rendered manifests.yaml> <cases.json>
//
// cases.json: [{"name", "expect": "allow"|"deny", "operation", "resource",
// "subResource", "group", "version", "kind", "namespace", "name_",
// "username", "object", "oldObject", "namespaceObject"}]
package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"

	admissionregistrationv1 "k8s.io/api/admissionregistration/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	utilyaml "k8s.io/apimachinery/pkg/util/yaml"
	"k8s.io/apiserver/pkg/admission"
	plugincel "k8s.io/apiserver/pkg/admission/plugin/cel"
	"k8s.io/apiserver/pkg/admission/plugin/policy/validating"
	"k8s.io/apiserver/pkg/admission/plugin/webhook/matchconditions"
	celconfig "k8s.io/apiserver/pkg/apis/cel"
	"k8s.io/apiserver/pkg/authentication/user"
	"k8s.io/apiserver/pkg/cel/environment"
)

type testCase struct {
	Name            string                 `json:"name"`
	Expect          string                 `json:"expect"`
	Operation       string                 `json:"operation"`
	Group           string                 `json:"group"`
	Version         string                 `json:"version"`
	Kind            string                 `json:"kind"`
	Resource        string                 `json:"resource"`
	SubResource     string                 `json:"subResource"`
	Namespace       string                 `json:"namespace"`
	ObjName         string                 `json:"name_"`
	Username        string                 `json:"username"`
	Object          map[string]interface{} `json:"object"`
	OldObject       map[string]interface{} `json:"oldObject"`
	NamespaceObject map[string]interface{} `json:"namespaceObject"`
}

func loadPolicy(path string) (*admissionregistrationv1.ValidatingAdmissionPolicy, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	reader := utilyaml.NewYAMLReader(bufio.NewReader(f))
	for {
		doc, err := reader.Read()
		if err == io.EOF {
			return nil, fmt.Errorf("no ValidatingAdmissionPolicy in %s", path)
		}
		if err != nil {
			return nil, err
		}
		if !bytes.Contains(doc, []byte("kind: ValidatingAdmissionPolicy\n")) {
			continue
		}
		var policy admissionregistrationv1.ValidatingAdmissionPolicy
		if err := utilyaml.NewYAMLOrJSONDecoder(bytes.NewReader(doc), 4096).Decode(&policy); err != nil {
			return nil, err
		}
		return &policy, nil
	}
}

// compile mirrors compilePolicy in k8s.io/apiserver/pkg/admission/plugin/policy/validating/plugin.go.
func compile(policy *admissionregistrationv1.ValidatingAdmissionPolicy) validating.Validator {
	strictCost := true
	optionalVars := plugincel.OptionalVariableDeclarations{HasParams: false, HasAuthorizer: true, StrictCost: strictCost}
	expressionOptionalVars := plugincel.OptionalVariableDeclarations{HasParams: false, HasAuthorizer: false, StrictCost: strictCost}
	env, err := plugincel.NewCompositionEnv(plugincel.VariablesTypeName, environment.MustBaseEnvSet(environment.DefaultCompatibilityVersion(), strictCost))
	if err != nil {
		panic(err)
	}
	compiler := plugincel.NewCompositedCompilerFromTemplate(env)
	var variables []plugincel.NamedExpressionAccessor
	for _, v := range policy.Spec.Variables {
		variables = append(variables, &validating.Variable{Name: v.Name, Expression: v.Expression})
	}
	compiler.CompileAndStoreVariables(variables, optionalVars, environment.StoredExpressions)

	var matchAccessors []plugincel.ExpressionAccessor
	for i := range policy.Spec.MatchConditions {
		matchAccessors = append(matchAccessors, (*matchconditions.MatchCondition)(&policy.Spec.MatchConditions[i]))
	}
	matcher := matchconditions.NewMatcher(compiler.Compile(matchAccessors, optionalVars, environment.StoredExpressions), policy.Spec.FailurePolicy, "policy", "validate", policy.Name)

	var validations, messages []plugincel.ExpressionAccessor
	for _, v := range policy.Spec.Validations {
		validations = append(validations, &validating.ValidationCondition{Expression: v.Expression, Message: v.Message, Reason: v.Reason})
		messages = append(messages, &validating.MessageExpressionCondition{MessageExpression: v.MessageExpression})
	}
	return validating.NewValidator(
		compiler.Compile(validations, optionalVars, environment.StoredExpressions),
		matcher,
		compiler.Compile(nil, optionalVars, environment.StoredExpressions),
		compiler.Compile(messages, expressionOptionalVars, environment.StoredExpressions),
		policy.Spec.FailurePolicy,
	)
}

func toObject(m map[string]interface{}) runtime.Object {
	if m == nil {
		return nil
	}
	return &unstructured.Unstructured{Object: m}
}

func run(validator validating.Validator, c testCase) (string, string) {
	gvr := schema.GroupVersionResource{Group: c.Group, Version: c.Version, Resource: c.Resource}
	gvk := schema.GroupVersionKind{Group: c.Group, Version: c.Version, Kind: c.Kind}
	attrs := admission.NewAttributesRecord(
		toObject(c.Object), toObject(c.OldObject), gvk, c.Namespace, c.ObjName, gvr, c.SubResource,
		admission.Operation(c.Operation), nil, false, &user.DefaultInfo{Name: c.Username},
	)
	versioned := &admission.VersionedAttributes{Attributes: attrs, VersionedKind: gvk,
		VersionedObject: toObject(c.Object), VersionedOldObject: toObject(c.OldObject)}
	var ns *corev1.Namespace
	if c.NamespaceObject != nil {
		ns = &corev1.Namespace{}
		if err := runtime.DefaultUnstructuredConverter.FromUnstructured(c.NamespaceObject, ns); err != nil {
			panic(err)
		}
	}
	result := validator.Validate(context.Background(), gvr, versioned, nil, ns, celconfig.RuntimeCELCostBudget, nil)
	for _, d := range result.Decisions {
		if d.Action == validating.ActionDeny {
			return "deny", d.Message
		}
	}
	return "allow", ""
}

func main() {
	policy, err := loadPolicy(os.Args[1])
	if err != nil {
		panic(err)
	}
	raw, err := os.ReadFile(os.Args[2])
	if err != nil {
		panic(err)
	}
	var cases []testCase
	if err := json.Unmarshal(raw, &cases); err != nil {
		panic(err)
	}
	validator := compile(policy)
	failed := 0
	for _, c := range cases {
		got, message := run(validator, c)
		status := "ok  "
		if got != c.Expect {
			status = "FAIL"
			failed++
		}
		fmt.Printf("%s %-5s %s", status, got, c.Name)
		if message != "" {
			m := strings.Join(strings.Fields(message), " "); if len(m) > 160 { m = m[:160] + "..." }; fmt.Printf("   [%s]", m)
		}
		fmt.Println()
	}
	fmt.Printf("\n%d cases, %d failed\n", len(cases), failed)
	if failed > 0 {
		os.Exit(1)
	}
}
